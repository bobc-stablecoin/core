"""Independent BOBC accounting and state transition properties."""
from hypothesis.stateful import invariant

from tests.utils.protocol import ZERO_ADDRESS, is_zero, same


class Properties:
    def check_opened_position(self, borrower, debt, assets, supply_before, balance_before):
        """fyzz: SP-01 | Accounting | A successful open mints the recorded debt."""
        pos = self.protocol.engine.position(borrower)
        assert pos[5], "SP-01: opened position must exist"
        assert pos[1] == debt, "SP-01: recorded debt must equal requested debt"
        assert pos[0] > 0, "SP-01: opened position must hold shares"
        assert self.protocol.engine.collateral_assets(borrower) > 0, "SP-01: collateral value must be positive"
        assert self.protocol.bobc.totalSupply() == supply_before + debt, "SP-01: supply must increase by minted debt"
        assert self.protocol.bobc.balanceOf(borrower) == balance_before + debt, "SP-01: borrower must receive minted debt"

    def check_position_collateral_increased(self, borrower, shares_before, balance_before, assets):
        """fyzz: SP-02 | Accounting | Added collateral increases shares and spends assets."""
        pos = self.protocol.engine.position(borrower)
        assert pos[0] > shares_before, "SP-02: added collateral must increase position shares"
        assert self.protocol.asset.balanceOf(borrower) == balance_before - assets, "SP-02: borrower must spend deposited crvUSD"

    def check_withdraw_keeps_minimum_ratio(self, borrower):
        """fyzz: SP-03 | Solvency | Withdrawal preserves the minimum collateral ratio."""
        assert self.protocol.engine.collateral_ratio(borrower) >= self.protocol.engine.MIN_CR(), "SP-03: withdrawal must preserve MIN_CR"

    def check_borrow_minted(self, borrower, debt_before, pending_before, balance_before, amount):
        """fyzz: SP-04 | Accounting | Additional debt and minted balance agree."""
        pos = self.protocol.engine.position(borrower)
        assert pos[1] == debt_before + pending_before + amount, "SP-04: debt must include accrued fees and new borrowing"
        assert self.protocol.bobc.balanceOf(borrower) == balance_before + amount, "SP-04: borrower must receive borrowed BOBC"

    def check_repayment(self, borrower, debt_before, fees_before, pending_before, balance_before, amount):
        """fyzz: SP-05 | Accounting | Repayment burns principal after accruing fees."""
        pos = self.protocol.engine.position(borrower)
        assert pos[1] == debt_before + pending_before - amount, "SP-05: debt must accrue fees then subtract repayment"
        assert pos[2] == fees_before + pending_before, "SP-05: accrued interest must remain recorded as fees"
        assert self.protocol.bobc.balanceOf(borrower) == balance_before - amount, "SP-05: repayment must burn caller BOBC"

    def check_position_closed(self, borrower, collateral_before, asset_balance_before):
        """fyzz: SP-06 | Accounting | Closure clears the position and returns collateral."""
        pos = self.protocol.engine.position(borrower)
        assert not pos[5], "SP-06: closed position must be unlinked"
        assert pos[0] == pos[1] == pos[2] == 0, "SP-06: closed position shares and debt must be zero"
        assert self.protocol.asset.balanceOf(borrower) == asset_balance_before + collateral_before, "SP-06: borrower must receive collateral"

    def check_rate_changed(self, borrower, annual_rate):
        """fyzz: SP-07 | Structure | A rate change stores the requested rate."""
        assert self.protocol.engine.position(borrower)[3] == annual_rate, "SP-07: position must store the requested rate"

    def check_transfer(self, supply_before, holder, receiver, balances_before, amount):
        """fyzz: SP-08 | Accounting | BOBC transfer conserves supply and amount."""
        holder_before, receiver_before = balances_before
        assert self.protocol.bobc.totalSupply() == supply_before, "SP-08: transfer must preserve total supply"
        assert self.protocol.bobc.balanceOf(holder) == holder_before - amount, "SP-08: transfer must debit sender"
        assert self.protocol.bobc.balanceOf(receiver) == receiver_before + amount, "SP-08: transfer must credit receiver"

    def check_supply_unchanged(self, supply_before):
        """fyzz: SP-09 | Accounting | Funding transfers preminted BOBC without minting."""
        assert self.protocol.bobc.totalSupply() == supply_before, "SP-09: funding must not increase BOBC supply"

    def check_cashback_payment(
        self, payer, merchant, amount, rebate, returned_rebate,
        supply_before, balances_before,
    ):
        """fyzz: SP-10 | Accounting | Payment and rebate conserve inventory and supply."""
        payer_before, merchant_before, pool_before = balances_before
        assert returned_rebate == rebate, "SP-10: returned rebate must match rounded rebate"
        assert self.protocol.bobc.totalSupply() == supply_before, "SP-10: payment must preserve total supply"
        assert self.protocol.bobc.balanceOf(payer) == payer_before - amount + rebate, "SP-10: payer balance must include payment and rebate"
        assert self.protocol.bobc.balanceOf(merchant) == merchant_before + amount, "SP-10: merchant must receive the payment"
        assert self.protocol.bobc.balanceOf(self.protocol.cashback.address) == pool_before - rebate, "SP-10: inventory must fund the rebate"

    def check_redemption(
        self, holder, requested, assets_out, token_before, asset_before,
        shares_before, positions_before,
    ):
        """fyzz: SP-17 | Accounting | Redemption burns principal and returns collateral."""
        token_after = self.protocol.bobc.balanceOf(holder)
        asset_after = self.protocol.asset.balanceOf(holder)
        paid = token_before - token_after
        assert 0 < paid <= requested, "SP-17: redemption must burn no more than requested BOBC"
        assert assets_out > 0, "SP-17: successful redemption must return assets"
        # A final redemption also returns any residual position shares to that
        # borrower. If the holder owns the redeemed position, their total asset
        # increase is therefore the direct redemption output plus that remainder.
        assert asset_after - asset_before >= assets_out, "SP-17: redeemer or borrower must receive returned assets"
        assert self.protocol.engine.total_shares() < shares_before, "SP-17: redemption must reduce assigned shares"
        principal_before = sum(pos[1] - pos[2] for pos in positions_before if pos[5])
        principal_after = 0
        for borrower in self.model.borrowers:
            pos = self.protocol.engine.position(borrower)
            if pos[5]:
                assert pos[1] >= self.protocol.engine.MIN_DEBT(), "SP-17: surviving debt must respect the floor"
                principal_after += pos[1] - pos[2]
        assert principal_before - principal_after == paid, "SP-17: principal reduction must equal BOBC burned"

    def check_liquidation(
        self, borrower, liquidator, position_before, assets_before, rate_before,
        pending_before, insurance_before, bad_debt_before, debt_total_before, shares_total_before,
        surplus_before, supply_before, liquidator_tokens_before,
        liquidator_assets_before, borrower_assets_before,
    ):
        """fyzz: SP-18 | Solvency | Liquidation matches independent payout arithmetic."""
        engine = self.protocol.engine
        bobc = self.protocol.bobc
        debt, fees, shares = position_before[1], position_before[2], position_before[0]
        assert not engine.position(borrower)[5], "SP-18: liquidated position must be unlinked"
        # Boa uses a stable block timestamp for this synchronous local machine;
        # pending_interest was read in the same timestamp before the call.
        accrued = pending_before
        effective_debt = debt + accrued
        effective_fees = fees + accrued
        debt_assets = effective_debt * 10**18 // rate_before
        principal = effective_debt - effective_fees

        if assets_before >= debt_assets:
            liq_assets = debt_assets * (10_000 + engine.LIQUIDATOR_BPS()) // 10_000
            if liq_assets > assets_before:
                liq_assets = assets_before
            insurance_assets = debt_assets * engine.INSURANCE_BPS() // 10_000
            if liq_assets + insurance_assets > assets_before:
                insurance_assets = max(0, assets_before - liq_assets)
            borrower_assets = assets_before - liq_assets - insurance_assets
            insurance_spent = 0
            liquidator_bobc = principal
            fee_burn = effective_fees
            bad_debt = 0
        else:
            insurance_spent = min(insurance_before, debt_assets - assets_before)
            liq_assets = assets_before + insurance_spent
            insurance_assets = 0
            borrower_assets = 0
            value_paid = min(effective_debt, liq_assets * rate_before // 10**18)
            fee_burn = min(effective_fees, max(0, value_paid - principal))
            liquidator_bobc = value_paid - fee_burn
            bad_debt = effective_debt - liquidator_bobc - fee_burn

        assert engine.total_debt() == debt_total_before - debt, "SP-18: liquidation must remove position debt"
        assert engine.total_shares() == shares_total_before - shares, "SP-18: liquidation must remove position shares"
        assert engine.insurance_assets() == insurance_before - insurance_spent + insurance_assets, "SP-18: insurance must follow payout branch"
        assert engine.bad_debt() == bad_debt_before + bad_debt, "SP-18: uncovered debt must be recorded"
        assert bobc.balanceOf(liquidator) == liquidator_tokens_before - liquidator_bobc, "SP-18: liquidator BOBC burn must match payout"
        assert self.protocol.asset.balanceOf(liquidator) == liquidator_assets_before + liq_assets, "SP-18: liquidator assets must match payout"
        assert self.protocol.asset.balanceOf(borrower) == borrower_assets_before + borrower_assets, "SP-18: borrower remainder must match payout"
        assert engine.surplus() == surplus_before + accrued - fee_burn, "SP-18: fee surplus must account for accrued and burned fees"
        assert bobc.totalSupply() == supply_before + accrued - liquidator_bobc - fee_burn, "SP-18: BOBC supply must reflect mint and burns"
        assert engine.insurance_assets() == self.protocol.asset.balanceOf(engine.address), "SP-18: idle crvUSD must equal insurance"

    def _check_supply_debt(self):
        assert self.protocol.bobc.totalSupply() == (
            self.protocol.engine.total_debt() + self.protocol.engine.bad_debt()
        ), "GL-01: supply must equal live debt plus bad debt"

    @invariant()
    def global_supply_matches_debt_and_bad_debt(self):
        """fyzz: GL-01 | Accounting | Supply equals live plus orphaned debt."""
        self.diagnostics.check("GL-01", self._check_supply_debt)

    def _check_engine_surplus(self):
        assert self.protocol.bobc.balanceOf(self.protocol.engine.address) == self.protocol.engine.surplus(), "GL-02: engine BOBC must equal fee surplus"

    @invariant()
    def global_engine_bobc_is_fee_surplus(self):
        """fyzz: GL-02 | Accounting | Engine BOBC is exactly accrued fee surplus."""
        self.diagnostics.check("GL-02", self._check_engine_surplus)

    def _check_position_books_and_list(self):
        engine = self.protocol.engine
        debt_sum = 0
        shares_sum = 0
        seen = set()
        current = engine.head()
        previous_rate = 0
        while not is_zero(current):
            assert current not in seen, "GL-03: position list contains a cycle"
            seen.add(current)
            pos = engine.position(current)
            assert pos[5], "GL-03: every listed position must be active"
            assert pos[3] >= previous_rate, "GL-03: position rates must be nondecreasing"
            assert pos[1] > pos[2], "GL-03: linked position must retain redeemable principal"
            debt_sum += pos[1]
            shares_sum += pos[0]
            previous_rate = pos[3]
            current = engine.next(current)
        expected = set()
        for borrower in self.model.borrowers:
            pos = engine.position(borrower)
            if pos[5]:
                expected.add(borrower)
                assert borrower in seen, "GL-03: every modeled open borrower must be linked"
            else:
                assert borrower not in seen, "GL-03: closed borrower must be unlinked"
                assert pos[0] == pos[1] == pos[2] == 0, "GL-03: closed borrower position must be empty"
        assert seen == expected, "GL-03: list membership must match modeled open borrowers"
        assert debt_sum == engine.total_debt(), "GL-03: listed debt must equal total debt"
        assert shares_sum == engine.total_shares(), "GL-03: listed shares must equal total shares"

    @invariant()
    def global_position_books_and_ordered_acyclic_list(self):
        """fyzz: GL-03 | Structure | Listed borrowers equal stored positions and totals."""
        self.diagnostics.check("GL-03", self._check_position_books_and_list)

    def _check_idle_insurance_balance(self):
        assert self.protocol.asset.balanceOf(self.protocol.engine.address) == (
            self.protocol.engine.insurance_assets()
        ), "GL-04: engine idle crvUSD must equal insurance assets"

    @invariant()
    def global_idle_crvusd_is_accounted_as_insurance(self):
        """fyzz: GL-04 | Accounting | Engine idle crvUSD equals recorded insurance."""
        self.diagnostics.check("GL-04", self._check_idle_insurance_balance)

    def _check_merchants(self):
        cashback = self.protocol.cashback
        actual = list(cashback.get_merchants())
        assert len(actual) == len(set(actual)), "GL-05: merchant array must be unique"
        assert set(actual) == self.model.approved_merchants, "GL-05: merchant list must match model"
        for merchant in self.model.merchants:
            assert cashback.is_merchant(merchant) == (merchant in self.model.approved_merchants), "GL-05: membership map must match merchant list"

    @invariant()
    def global_cashback_list_matches_membership_map(self):
        """fyzz: GL-05 | Access | Merchant array and membership map stay synchronized."""
        self.diagnostics.check("GL-05", self._check_merchants)

    def _check_cashback_owner(self):
        assert same(self.protocol.cashback.owner(), self.model.owner), "GL-06: owner must match two-step model"
        expected_pending = self.model.pending_owner or ZERO_ADDRESS
        assert same(self.protocol.cashback.pending_owner(), expected_pending), "GL-06: pending owner must match two-step model"

    @invariant()
    def global_cashback_ownership_model_matches_chain(self):
        """fyzz: GL-06 | Access | Two step ownership changes track the modeled owner."""
        self.diagnostics.check("GL-06", self._check_cashback_owner)
