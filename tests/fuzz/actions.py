"""Stateful protocol actions and deliberate rejection cases."""
import boa
from hypothesis import strategies as st
from hypothesis.stateful import initialize, precondition, rule

from tests.utils.protocol import (
    MAX_UINT256,
    MIN_CR,
    MIN_DEBT,
    ONE,
    RATE_LOW,
    ZERO_ADDRESS,
    YEAR,
    deploy_engine,
    hints_for,
)
from .strategies import collateral_amounts, near_limit_debt, oracle_rates, rates


class Actions:
    @property
    def protocol(self):
        return self.deployment.protocol

    @property
    def model(self):
        return self.deployment.model

    @property
    def actors(self):
        return (
            self.model.deployer,
            *self.model.borrowers,
            *self.model.holders,
            *self.model.liquidators,
            *self.model.merchants,
        )

    def _fresh_oracle(self) -> bool:
        rate, updated_at = self.protocol.oracle.latest()
        return (
            rate > 0
            and updated_at <= boa.env.timestamp
            and boa.env.timestamp - updated_at <= self.protocol.engine.MAX_STALENESS()
        )

    def _position(self, borrower: str):
        return self.protocol.engine.position(borrower)

    @initialize()
    def initialize_core_positions(self):
        """Seed one redeemable position and one independent borrower book."""
        initial = (
            (self.model.borrowers[0], 1_430 * ONE, RATE_LOW),
            (self.model.borrowers[1], 2_860 * ONE, 8 * 10**16),
        )
        for borrower, assets, annual_rate in initial:
            debt = assets * ONE // MIN_CR // 2
            prev, nxt = hints_for(self.protocol.engine, annual_rate)
            supply_before = self.protocol.bobc.totalSupply()
            balance_before = self.protocol.bobc.balanceOf(borrower)
            with self.diagnostics.action(
                "open_position",
                inputs={"actor": borrower, "assets": assets, "debt": debt,
                        "annual_rate": annual_rate, "initializer": True},
                transition="collateral_deposited_to_borrower_debt_minted",
            ):
                self.protocol.engine.open_position(
                    assets, debt, annual_rate, prev, nxt, sender=borrower
                )
                self.diagnostics.check(
                    "SP-01", lambda b=borrower, d=debt, a=assets, s=supply_before,
                    t=balance_before: self.check_opened_position(b, d, a, s, t)
                )

        holder = self.model.holders[0]
        donor = self.model.borrowers[1]
        amount = 400 * ONE
        supply_before = self.protocol.bobc.totalSupply()
        balances_before = (
            self.protocol.bobc.balanceOf(donor), self.protocol.bobc.balanceOf(holder)
        )
        with self.diagnostics.action(
            "transfer_bobc", inputs={"actor": donor, "receiver": holder,
                                     "amount": amount, "initializer": True},
            transition="bobc_transferred_between_actors",
        ):
            self.protocol.bobc.transfer(holder, amount, sender=donor)
            self.diagnostics.check(
                "SP-08",
                lambda: self.check_transfer(
                    supply_before, donor, holder, balances_before, amount
                ),
            )

        merchant = self.model.merchants[0]
        with self.diagnostics.action(
            "add_merchant", inputs={"actor": self.model.owner, "merchant": merchant,
                                    "initializer": True},
        ):
            self.protocol.cashback.add_merchant(merchant, sender=self.model.owner)
            self.model.approved_merchants.add(merchant)

    def _open_borrowers(self) -> list[str]:
        return [actor for actor in self.model.borrowers if self._position(actor)[5]]

    def _free_borrowers(self) -> list[str]:
        return [actor for actor in self.model.borrowers if not self._position(actor)[5]]

    def _cashback_pool_has(self, amount: int) -> bool:
        return self.protocol.bobc.balanceOf(self.protocol.cashback.address) >= amount

    def _vault_assets(self) -> int:
        return self.protocol.vault.convertToAssets(self.protocol.engine.total_shares())

    def _assert_unchanged_after_revert(self, property_id, call, snapshot, read_snapshot):
        try:
            call()
        except boa.BoaError:
            assert read_snapshot() == snapshot, f"{property_id}: rejected call changed state"
            raise
        assert read_snapshot() == snapshot, f"{property_id}: call did not revert and changed state"

    @rule(borrower_index=st.integers(0, 2), assets=collateral_amounts(), annual_rate=rates())
    @precondition(lambda self: self._fresh_oracle() and bool(self._free_borrowers()))
    def open_position(self, borrower_index: int, assets: int, annual_rate: int):
        """Open a supported borrower position at its current collateral limit."""
        candidates = self._free_borrowers()
        borrower = candidates[borrower_index % len(candidates)]
        rate, _ = self.protocol.oracle.latest()
        debt = near_limit_debt(self.protocol.vault, self.protocol.asset, assets, rate, MIN_CR)
        if debt < MIN_DEBT or self.protocol.asset.balanceOf(borrower) < assets:
            return
        if self._vault_assets() + assets > self.protocol.engine.MAX_COLLATERAL_ASSETS():
            return
        prev, nxt = hints_for(self.protocol.engine, annual_rate)
        supply_before = self.protocol.bobc.totalSupply()
        balance_before = self.protocol.bobc.balanceOf(borrower)
        with self.diagnostics.action(
            "open_position",
            inputs={"actor": borrower, "assets": assets, "debt": debt, "annual_rate": annual_rate,
                    "prev": prev, "next": nxt},
            transition="collateral_deposited_to_borrower_debt_minted",
        ):
            self.protocol.engine.open_position(
                assets, debt, annual_rate, prev, nxt, sender=borrower
            )
            self.diagnostics.check(
                "SP-01", lambda: self.check_opened_position(
                    borrower, debt, assets, supply_before, balance_before
                )
            )

    @rule(borrower_index=st.integers(0, 2), asset_units=st.integers(1, 250))
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def add_collateral(self, borrower_index: int, asset_units: int):
        borrower = self.model.borrowers[borrower_index]
        pos = self._position(borrower)
        if not pos[5] or self.protocol.asset.balanceOf(borrower) < ONE:
            return
        assets = min(asset_units * ONE, self.protocol.asset.balanceOf(borrower))
        assets = min(assets, 100 * ONE)
        if assets == 0:
            return
        before = self._position(borrower)
        balance_before = self.protocol.asset.balanceOf(borrower)
        with self.diagnostics.action(
            "add_collateral", inputs={"actor": borrower, "assets": assets},
            transition="existing_position_receives_collateral",
        ):
            self.protocol.engine.add_collateral(assets, sender=borrower)
            self.diagnostics.check(
                "SP-02", lambda: self.check_position_collateral_increased(
                    borrower, before[0], balance_before, assets
                )
            )

    @rule(borrower_index=st.integers(0, 2), asset_units=st.integers(1, 100))
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def withdraw_collateral(self, borrower_index: int, asset_units: int):
        borrower = self.model.borrowers[borrower_index]
        pos = self._position(borrower)
        if not pos[5]:
            return
        assets = self.protocol.engine.collateral_assets(borrower)
        debt = pos[1] + self.protocol.engine.pending_interest(borrower)
        rate, _ = self.protocol.oracle.latest()
        minimum = (debt * self.protocol.engine.MIN_CR() + rate - 1) // rate
        cushion = assets - minimum - 2
        if cushion < 2 * ONE:
            return
        amount = min(asset_units * ONE, cushion // 2, 10 * ONE)
        if amount <= 0:
            return
        with self.diagnostics.action(
            "withdraw_collateral", inputs={"actor": borrower, "assets": amount},
            transition="position_collateral_withdrawn_above_minimum_ratio",
        ):
            self.protocol.engine.withdraw_collateral(amount, sender=borrower)
            self.diagnostics.check(
                "SP-03", lambda: self.check_withdraw_keeps_minimum_ratio(borrower)
            )

    @rule(borrower_index=st.integers(0, 2), debt_units=st.integers(1, 100))
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def borrow_more(self, borrower_index: int, debt_units: int):
        borrower = self.model.borrowers[borrower_index]
        pos = self._position(borrower)
        if not pos[5]:
            return
        held = self.protocol.engine.collateral_assets(borrower)
        rate, _ = self.protocol.oracle.latest()
        current = pos[1] + self.protocol.engine.pending_interest(borrower)
        capacity = (held * rate // ONE) * ONE // self.protocol.engine.MIN_CR()
        room = capacity - current - 2
        if room < 2 * ONE:
            return
        amount = min(debt_units * ONE, room // 2, 10 * ONE)
        debt_before = pos[1]
        pending_before = self.protocol.engine.pending_interest(borrower)
        balance_before = self.protocol.bobc.balanceOf(borrower)
        with self.diagnostics.action(
            "borrow", inputs={"actor": borrower, "amount": amount},
            transition="position_debt_increased_with_new_bobc",
        ):
            self.protocol.engine.borrow(amount, sender=borrower)
            self.diagnostics.check(
                "SP-04", lambda: self.check_borrow_minted(
                    borrower, debt_before, pending_before, balance_before, amount
                )
            )

    @rule(borrower_index=st.integers(0, 2), debt_units=st.integers(1, 500))
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def repay(self, borrower_index: int, debt_units: int):
        borrower = self.model.borrowers[borrower_index]
        pos = self._position(borrower)
        if not pos[5]:
            return
        principal = pos[1] - pos[2]
        if principal <= 1:
            return
        max_principal = min(principal - 1, pos[1] - MIN_DEBT)
        amount = min(debt_units * ONE, max_principal, self.protocol.bobc.balanceOf(borrower))
        if amount <= 0:
            return
        pending_before = self.protocol.engine.pending_interest(borrower)
        fees_before = pos[2]
        balance_before = self.protocol.bobc.balanceOf(borrower)
        with self.diagnostics.action(
            "repay", inputs={"actor": borrower, "amount": amount},
            transition="borrower_burns_principal",
        ):
            self.protocol.engine.repay(amount, sender=borrower)
            self.diagnostics.check(
                "SP-05", lambda: self.check_repayment(
                    borrower, pos[1], fees_before, pending_before, balance_before, amount
                )
            )

    def _fee_only_repay_candidates(self) -> list[str]:
        candidates = []
        for borrower in self._open_borrowers():
            pos = self._position(borrower)
            principal = pos[1] - pos[2]
            yearly_interest = pos[1] * pos[3] // ONE
            accrued = self.protocol.engine.pending_interest(borrower)
            if (
                principal > 0
                and self.protocol.bobc.balanceOf(borrower) >= principal
                and pos[2] + accrued + yearly_interest >= self.protocol.engine.MIN_DEBT()
            ):
                candidates.append(borrower)
        return candidates

    @rule(borrower_index=st.integers(0, 10))
    @precondition(lambda self: self._fresh_oracle() and bool(self._fee_only_repay_candidates()))
    def final_principal_repayment_reverts(self, borrower_index: int):
        """fyzz: SP-20 | Structure | Final principal repayment cannot leave a fee-only node."""
        candidates = self._fee_only_repay_candidates()
        borrower = candidates[borrower_index % len(candidates)]
        pos = self._position(borrower)
        principal = pos[1] - pos[2]
        boa.env.time_travel(seconds=YEAR)
        rate, _ = self.protocol.oracle.latest()
        self.protocol.oracle.setUpdatedAt(boa.env.timestamp)
        assert pos[2] + self.protocol.engine.pending_interest(borrower) >= (
            self.protocol.engine.MIN_DEBT()
        )
        snapshots = (
            self._position(borrower),
            self.protocol.bobc.balanceOf(borrower),
            self.protocol.engine.total_debt(),
            self.protocol.engine.surplus(),
            self.protocol.bobc.totalSupply(),
        )
        with self.diagnostics.action(
            "final_principal_repay_revert",
            inputs={"borrower": borrower, "principal": principal, "elapsed": YEAR,
                    "oracle_rate": rate},
            expected_revert=(boa.BoaError,), match="Engine: close position",
        ):
            self._assert_unchanged_after_revert(
                "SP-20",
                lambda: self.protocol.engine.repay(principal, sender=borrower),
                snapshots,
                lambda: (
                    self._position(borrower),
                    self.protocol.bobc.balanceOf(borrower),
                    self.protocol.engine.total_debt(),
                    self.protocol.engine.surplus(),
                    self.protocol.bobc.totalSupply(),
                ),
            )
            self.diagnostics.check(
                "SP-20",
                lambda: self.protocol.engine.position(borrower)[1]
                > self.protocol.engine.position(borrower)[2],
            )
            assert self.protocol.engine.position(borrower)[1] > self.protocol.engine.position(borrower)[2], "SP-20: listed position must retain principal"

    @rule(borrower_index=st.integers(0, 2))
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def close_position(self, borrower_index: int):
        borrower = self.model.borrowers[borrower_index]
        pos = self._position(borrower)
        if not pos[5]:
            return
        principal = pos[1] - pos[2]
        if self.protocol.bobc.balanceOf(borrower) < principal:
            return
        collateral_before = self.protocol.engine.collateral_assets(borrower)
        asset_balance_before = self.protocol.asset.balanceOf(borrower)
        with self.diagnostics.action(
            "close_position", inputs={"actor": borrower, "principal": principal},
            transition="position_closed_and_collateral_returned",
        ):
            self.protocol.engine.close_position(sender=borrower)
            self.diagnostics.check(
                "SP-06", lambda: self.check_position_closed(
                    borrower, collateral_before, asset_balance_before
                )
            )

    @rule(borrower_index=st.integers(0, 2), annual_rate=rates())
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def set_rate(self, borrower_index: int, annual_rate: int):
        borrower = self.model.borrowers[borrower_index]
        if not self._position(borrower)[5]:
            return
        prev, nxt = hints_for(self.protocol.engine, annual_rate, skip=borrower)
        with self.diagnostics.action(
            "set_rate", inputs={"actor": borrower, "annual_rate": annual_rate,
                                "prev": prev, "next": nxt},
            transition="position_rate_reordered",
        ):
            self.protocol.engine.set_rate(annual_rate, prev, nxt, sender=borrower)
            self.diagnostics.check("SP-07", lambda: self.check_rate_changed(borrower, annual_rate))

    @rule(holder_index=st.integers(0, 10), receiver_index=st.integers(0, 10), token_units=st.integers(1, 1_000))
    def transfer_bobc(self, holder_index: int, receiver_index: int, token_units: int):
        holder = self.actors[holder_index % len(self.actors)]
        receiver = self.actors[receiver_index]
        balance = self.protocol.bobc.balanceOf(holder)
        amount = min(token_units * ONE, balance)
        if holder == receiver or amount <= 0:
            return
        supply_before = self.protocol.bobc.totalSupply()
        balances_before = (balance, self.protocol.bobc.balanceOf(receiver))
        with self.diagnostics.action(
            "transfer_bobc", inputs={"actor": holder, "receiver": receiver, "amount": amount},
            transition="bobc_transferred_between_actors",
        ):
            self.protocol.bobc.transfer(receiver, amount, sender=holder)
            self.diagnostics.check(
                "SP-08",
                lambda: self.check_transfer(supply_before, holder, receiver, balances_before, amount),
            )

    @rule(holder_index=st.integers(0, 10), amount_units=st.integers(1, 10_000))
    def approve_cashback(self, holder_index: int, amount_units: int):
        holder = self.actors[holder_index]
        amount = min(amount_units * ONE, MAX_UINT256)
        with self.diagnostics.action(
            "approve_cashback", inputs={"actor": holder, "amount": amount}
        ):
            self.protocol.bobc.approve(self.protocol.cashback.address, amount, sender=holder)

    @rule(actor_index=st.integers(0, 10), receiver_index=st.integers(0, 10), amount_units=st.integers(1, 1_000))
    def fund_cashback(self, actor_index: int, receiver_index: int, amount_units: int):
        actor = self.actors[actor_index]
        receiver = self.protocol.cashback.address if receiver_index % 2 == 0 else self.model.deployer
        amount = min(amount_units * ONE, self.protocol.bobc.balanceOf(actor))
        if amount <= 0:
            return
        supply_before = self.protocol.bobc.totalSupply()
        with self.diagnostics.action(
            "fund_cashback", inputs={"actor": actor, "receiver": receiver, "amount": amount},
            transition="preminted_cashback_inventory_transferred",
        ):
            self.protocol.bobc.transfer(receiver, amount, sender=actor)
            self.diagnostics.check("SP-09", lambda: self.check_supply_unchanged(supply_before))

    @rule(rate_bps=st.integers(min_value=0, max_value=200))
    def configure_cashback_rate(self, rate_bps: int):
        with self.diagnostics.action(
            "set_cashback_bps", inputs={"actor": self.model.owner, "rate_bps": rate_bps}
        ):
            self.protocol.cashback.set_cashback_bps(rate_bps, sender=self.model.owner)

    @rule(merchant_index=st.integers(0, 2))
    def add_merchant(self, merchant_index: int):
        merchant = self.model.merchants[merchant_index]
        if merchant in self.model.approved_merchants or len(self.model.approved_merchants) >= 128:
            return
        with self.diagnostics.action(
            "add_merchant", inputs={"actor": self.model.owner, "merchant": merchant}
        ):
            self.protocol.cashback.add_merchant(merchant, sender=self.model.owner)
            self.model.approved_merchants.add(merchant)

    @rule(merchant_index=st.integers(0, 2))
    def remove_merchant(self, merchant_index: int):
        merchant = self.model.merchants[merchant_index]
        if merchant not in self.model.approved_merchants:
            return
        with self.diagnostics.action(
            "remove_merchant", inputs={"actor": self.model.owner, "merchant": merchant}
        ):
            self.protocol.cashback.remove_merchant(merchant, sender=self.model.owner)
            self.model.approved_merchants.remove(merchant)

    @rule(mask=st.integers(min_value=0, max_value=7))
    def replace_merchants(self, mask: int):
        merchants = [merchant for i, merchant in enumerate(self.model.merchants) if mask & (1 << i)]
        with self.diagnostics.action(
            "set_merchants", inputs={"actor": self.model.owner, "merchants": merchants}
        ):
            self.protocol.cashback.set_merchants(merchants, sender=self.model.owner)
            self.model.approved_merchants = set(merchants)

    @rule()
    def clear_merchants(self):
        with self.diagnostics.action("clear_merchants", inputs={"actor": self.model.owner}):
            self.protocol.cashback.clear_merchants(sender=self.model.owner)
            self.model.approved_merchants.clear()

    @rule(payer_index=st.integers(0, 10), merchant_index=st.integers(0, 2), amount_units=st.integers(1, 100))
    def pay_cashback(self, payer_index: int, merchant_index: int, amount_units: int):
        payer = self.actors[payer_index]
        merchant = self.model.merchants[merchant_index]
        if merchant not in self.model.approved_merchants or payer == merchant:
            return
        balance = self.protocol.bobc.balanceOf(payer)
        amount = min(amount_units * ONE, balance)
        if amount <= 0 or self.protocol.bobc.allowance(payer, self.protocol.cashback.address) < amount:
            return
        rebate = amount * self.protocol.cashback.CASHBACK_BPS() // 10_000
        if rebate > self.protocol.bobc.balanceOf(self.protocol.cashback.address):
            return
        supply_before = self.protocol.bobc.totalSupply()
        balances_before = (
            self.protocol.bobc.balanceOf(payer),
            self.protocol.bobc.balanceOf(merchant),
            self.protocol.bobc.balanceOf(self.protocol.cashback.address),
        )
        with self.diagnostics.action(
            "pay_cashback", inputs={"payer": payer, "merchant": merchant, "amount": amount},
            transition="payer_paid_merchant_and_received_inventory_rebate",
        ):
            returned_rebate = self.protocol.cashback.pay(merchant, amount, sender=payer)
            self.diagnostics.check(
                "SP-10",
                lambda: self.check_cashback_payment(
                    payer, merchant, amount, rebate, returned_rebate, supply_before, balances_before
                ),
            )

    @rule(rate=oracle_rates())
    def change_oracle_rate(self, rate: int):
        with self.diagnostics.action("oracle_set_rate", inputs={"rate": rate}):
            self.protocol.oracle.setRate(rate)

    @rule(seconds=st.integers(min_value=1, max_value=5_000))
    def advance_time(self, seconds: int):
        with self.diagnostics.action("time_travel", inputs={"seconds": seconds}):
            boa.env.time_travel(seconds=seconds)

    def refresh_oracle_timestamp(self):
        rate, _ = self.protocol.oracle.latest()
        with self.diagnostics.action("oracle_refresh", inputs={"rate": rate}):
            self.protocol.oracle.setUpdatedAt(boa.env.timestamp)

    @rule(asset_units=st.integers(min_value=1, max_value=10_000))
    def add_vault_yield(self, asset_units: int):
        assets = asset_units * ONE
        with self.diagnostics.action("vault_yield", inputs={"assets": assets}):
            self.protocol.asset.mint(self.protocol.vault.address, assets)

    @rule(asset_units=st.integers(min_value=1, max_value=1_000))
    def apply_vault_loss(self, asset_units: int):
        vault_balance = self.protocol.asset.balanceOf(self.protocol.vault.address)
        amount = min(asset_units * ONE, vault_balance // 2)
        if amount <= 0:
            return
        with self.diagnostics.action("vault_loss", inputs={"assets": amount}):
            self.protocol.asset.transfer(ZERO_ADDRESS, amount, sender=self.protocol.vault.address)

    @rule(holder_index=st.integers(0, 10), borrower_index=st.integers(0, 2), token_units=st.integers(1, 10_000))
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def redeem(self, holder_index: int, borrower_index: int, token_units: int):
        redeemers = [
            actor for actor in self.actors
            if self.protocol.bobc.balanceOf(actor) >= ONE
        ]
        if not redeemers:
            return
        holder = redeemers[holder_index % len(redeemers)]
        borrowers = [
            candidate for candidate in self._open_borrowers()
            if self.protocol.engine.position(candidate)[1] > self.protocol.engine.position(candidate)[2]
            and self.protocol.engine.collateral_assets(candidate) > 0
        ]
        if not borrowers:
            return
        borrower = borrowers[borrower_index % len(borrowers)]
        balance = self.protocol.bobc.balanceOf(holder)
        if balance < ONE:
            return
        amount = min(token_units * ONE, balance)
        if self.protocol.engine.collateral_ratio(borrower) < self.protocol.engine.LIQ_CR():
            pos = self._position(borrower)
            assets = self.protocol.engine.collateral_assets(borrower)
            debt = pos[1] + self.protocol.engine.pending_interest(borrower)
            rate = debt * self.protocol.engine.LIQ_CR() // assets + 1
            self.protocol.oracle.setRate(rate)
        if not self._redeemable_exists():
            return
        token_before = balance
        asset_before = self.protocol.asset.balanceOf(holder)
        shares_before = self.protocol.engine.total_shares()
        positions_before = tuple(
            self._position(borrower) for borrower in self.model.borrowers
        )
        with self.diagnostics.action(
            "redeem", inputs={"holder": holder, "amount": amount, "max_iterations": 32},
            transition="holder_burned_bobc_for_lowest_rate_collateral",
        ):
            assets_out = self.protocol.engine.redeem(amount, 32, sender=holder)
            self.diagnostics.check(
                "SP-17",
                lambda: self.check_redemption(
                    holder, amount, assets_out, token_before, asset_before,
                    shares_before, positions_before,
                ),
            )

    @rule(payer_index=st.integers(0, 10), merchant_index=st.integers(0, 2), amount_units=st.integers(1, 100))
    def complete_cashback_payment(self, payer_index: int, merchant_index: int, amount_units: int):
        merchant = self.model.merchants[merchant_index]
        payers = [
            actor for actor in self.actors
            if actor != merchant and self.protocol.bobc.balanceOf(actor) >= ONE
        ]
        if not payers:
            return
        payer = payers[payer_index % len(payers)]
        if payer == merchant:
            return
        payer_balance = self.protocol.bobc.balanceOf(payer)
        amount = min(amount_units * ONE, payer_balance)
        if amount < ONE:
            return

        owner = self.model.owner
        self.protocol.cashback.set_cashback_bps(100, sender=owner)
        if merchant not in self.model.approved_merchants:
            self.protocol.cashback.add_merchant(merchant, sender=owner)
            self.model.approved_merchants.add(merchant)

        rebate = amount * 100 // 10_000
        if rebate == 0:
            return
        pool = self.protocol.bobc.balanceOf(self.protocol.cashback.address)
        if pool < rebate:
            needed = rebate - pool
            donors = [
                actor for actor in self.actors
                if actor != payer and self.protocol.bobc.balanceOf(actor) >= needed
            ]
            if not donors:
                return
            donor = donors[payer_index % len(donors)]
            self.protocol.bobc.transfer(
                self.protocol.cashback.address, needed, sender=donor
            )

        self.protocol.bobc.approve(self.protocol.cashback.address, amount, sender=payer)
        supply_before = self.protocol.bobc.totalSupply()
        balances_before = (
            self.protocol.bobc.balanceOf(payer),
            self.protocol.bobc.balanceOf(merchant),
            self.protocol.bobc.balanceOf(self.protocol.cashback.address),
        )
        with self.diagnostics.action(
            "pay_cashback",
            inputs={"payer": payer, "merchant": merchant, "amount": amount,
                    "bps": 100, "inventory_prepared": True},
            transition="cashback_payment_completed_after_inventory_setup",
        ):
            returned_rebate = self.protocol.cashback.pay(merchant, amount, sender=payer)
            self.diagnostics.check(
                "SP-10",
                lambda: self.check_cashback_payment(
                    payer, merchant, amount, rebate, returned_rebate,
                    supply_before, balances_before,
                ),
            )

    @rule(liquidator_index=st.integers(0, 1), borrower_index=st.integers(0, 2))
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def liquidate(self, liquidator_index: int, borrower_index: int):
        liquidator = self.model.liquidators[liquidator_index]
        candidates = []
        for account in self._open_borrowers():
            pos = self._position(account)
            principal = pos[1] - pos[2]
            needed = max(0, principal - self.protocol.bobc.balanceOf(liquidator))
            if any(
                actor != liquidator and self.protocol.bobc.balanceOf(actor) >= needed
                for actor in self.actors
            ):
                candidates.append(account)
        if not candidates:
            return
        borrower = candidates[borrower_index % len(candidates)]
        pos = self._position(borrower)
        principal = pos[1] - pos[2]
        liquidator_balance = self.protocol.bobc.balanceOf(liquidator)
        if liquidator_balance < principal:
            needed = principal - liquidator_balance
            donors = [
                actor for actor in self.actors
                if actor != liquidator and self.protocol.bobc.balanceOf(actor) >= needed
            ]
            if not donors:
                return
            donor = donors[borrower_index % len(donors)]
            self.protocol.bobc.transfer(liquidator, needed, sender=donor)
        if self.protocol.engine.collateral_ratio(borrower) >= self.protocol.engine.LIQ_CR():
            assets = self.protocol.engine.collateral_assets(borrower)
            debt = pos[1] + self.protocol.engine.pending_interest(borrower)
            threshold_rate = debt * self.protocol.engine.LIQ_CR() // assets
            rate = max(1, threshold_rate - 1)
            self.protocol.oracle.setRate(rate)
        if self.protocol.bobc.balanceOf(liquidator) < principal:
            return
        position_before = self.protocol.engine.position(borrower)
        rate_before, _ = self.protocol.oracle.latest()
        assets_before = self.protocol.engine.collateral_assets(borrower)
        pending_before = self.protocol.engine.pending_interest(borrower)
        insurance_before = self.protocol.engine.insurance_assets()
        bad_debt_before = self.protocol.engine.bad_debt()
        debt_total_before = self.protocol.engine.total_debt()
        shares_total_before = self.protocol.engine.total_shares()
        surplus_before = self.protocol.engine.surplus()
        supply_before = self.protocol.bobc.totalSupply()
        liquidator_tokens_before = self.protocol.bobc.balanceOf(liquidator)
        liquidator_assets_before = self.protocol.asset.balanceOf(liquidator)
        borrower_assets_before = self.protocol.asset.balanceOf(borrower)
        with self.diagnostics.action(
            "liquidate", inputs={"liquidator": liquidator, "borrower": borrower},
            transition="undercollateralized_position_liquidated",
        ):
            self.protocol.engine.liquidate(borrower, sender=liquidator)
            self.diagnostics.check(
                "SP-18",
                lambda: self.check_liquidation(
                    borrower, liquidator, position_before, assets_before, rate_before,
                    pending_before, insurance_before, bad_debt_before, debt_total_before, shares_total_before,
                    surplus_before, supply_before, liquidator_tokens_before,
                    liquidator_assets_before, borrower_assets_before,
                ),
            )

    @rule(actor_index=st.integers(0, 10), amount=st.integers(min_value=1, max_value=MAX_UINT256))
    def unauthorized_mint(self, actor_index: int, amount: int):
        """fyzz: SP-11 | Access | Non-engine mint calls revert without changing balances."""
        actor = self.actors[actor_index]
        receiver = self.model.borrowers[0]
        supply_before = self.protocol.bobc.totalSupply()
        balance_before = self.protocol.bobc.balanceOf(receiver)
        with self.diagnostics.action(
            "unauthorized_mint", inputs={"actor": actor, "receiver": receiver, "amount": amount},
            expected_revert=(boa.BoaError,), match="BOBC: only engine",
        ):
            self._assert_unchanged_after_revert(
                "SP-11",
                lambda: self.protocol.bobc.mint(receiver, amount, sender=actor),
                (supply_before, balance_before),
                lambda: (self.protocol.bobc.totalSupply(), self.protocol.bobc.balanceOf(receiver)),
            )

    @rule(borrower_index=st.integers(0, 2))
    @precondition(lambda self: self._fresh_oracle() and bool(self._open_borrowers()))
    def stale_oracle_blocks_add_collateral(self, borrower_index: int):
        """fyzz: SP-12 | Oracle | Stale oracle rejection preserves collateral state."""
        borrower = self.model.borrowers[borrower_index]
        if not self._position(borrower)[5]:
            return
        boa.env.time_travel(seconds=self.protocol.engine.MAX_STALENESS() + 1)
        before = self._position(borrower)
        balances = (self.protocol.asset.balanceOf(borrower), self.protocol.engine.total_shares())
        with self.diagnostics.action(
            "expected_stale_oracle_revert", inputs={"borrower": borrower},
            expected_revert=(boa.BoaError,), match="Engine: stale oracle",
        ):
            self._assert_unchanged_after_revert(
                "SP-12",
                lambda: self.protocol.engine.add_collateral(ONE, sender=borrower),
                (before, balances),
                lambda: (
                    self._position(borrower),
                    (self.protocol.asset.balanceOf(borrower), self.protocol.engine.total_shares()),
                ),
            )

    @rule(borrower_index=st.integers(0, 2))
    @precondition(
        lambda self: self._fresh_oracle()
        and bool(self._open_borrowers())
        and self._vault_assets() + max(
            (self.protocol.asset.balanceOf(b) for b in self._open_borrowers()),
            default=0,
        ) + 1 <= self.protocol.engine.MAX_COLLATERAL_ASSETS()
    )
    def inadequate_collateral_balance_reverts(self, borrower_index: int):
        """fyzz: SP-19 | Accounting | Insufficient crvUSD balance reverts atomically."""
        borrower = self._open_borrowers()[borrower_index % len(self._open_borrowers())]
        balance = self.protocol.asset.balanceOf(borrower)
        amount = balance + 1
        position_before = self._position(borrower)
        books_before = (
            self.protocol.engine.total_debt(),
            self.protocol.engine.total_shares(),
            self.protocol.engine.surplus(),
            self.protocol.bobc.totalSupply(),
            self.protocol.asset.balanceOf(self.protocol.vault.address),
            self.protocol.vault.balanceOf(self.protocol.engine.address),
        )
        with self.diagnostics.action(
            "inadequate_collateral_balance",
            inputs={"borrower": borrower, "amount": amount, "balance": balance},
            expected_revert=(boa.BoaError,), match="ERC20: balance",
        ):
            self._assert_unchanged_after_revert(
                "SP-19",
                lambda: self.protocol.engine.add_collateral(amount, sender=borrower),
                (position_before, balance, books_before),
                lambda: (
                    self._position(borrower),
                    self.protocol.asset.balanceOf(borrower),
                    (
                        self.protocol.engine.total_debt(),
                        self.protocol.engine.total_shares(),
                        self.protocol.engine.surplus(),
                        self.protocol.bobc.totalSupply(),
                        self.protocol.asset.balanceOf(self.protocol.vault.address),
                        self.protocol.vault.balanceOf(self.protocol.engine.address),
                    ),
                ),
            )

    @rule()
    def refresh_oracle(self):
        self.refresh_oracle_timestamp()

    @rule()
    @precondition(lambda self: self._fresh_oracle() and bool(self._free_borrowers()))
    def invalid_list_hints_revert(self):
        """fyzz: SP-13 | Structure | Nonadjacent list hints revert without state changes."""
        borrower = self._free_borrowers()[0]
        if self.protocol.asset.balanceOf(borrower) < 1_500 * ONE:
            return
        rate, _ = self.protocol.oracle.latest()
        if rate == 0:
            return
        debt = near_limit_debt(
            self.protocol.vault, self.protocol.asset, 1_500 * ONE, rate, MIN_CR
        )
        prev = boa.env.generate_address("unlinked hint")
        before = (self.protocol.engine.total_debt(), self.protocol.bobc.totalSupply())
        with self.diagnostics.action(
            "invalid_list_hints", inputs={"borrower": borrower, "prev": prev, "next": ZERO_ADDRESS},
            expected_revert=(boa.BoaError,), match="List: bad hint",
        ):
            self._assert_unchanged_after_revert(
                "SP-13",
                lambda: self.protocol.engine.open_position(
                    1_500 * ONE, debt, RATE_LOW, prev, ZERO_ADDRESS, sender=borrower
                ),
                before,
                lambda: (self.protocol.engine.total_debt(), self.protocol.bobc.totalSupply()),
            )

    @rule()
    def invalid_cashback_limit_reverts(self):
        """fyzz: SP-14 | Access | Cashback rate above the cap reverts atomically."""
        before = self.protocol.cashback.CASHBACK_BPS()
        with self.diagnostics.action(
            "cashback_limit_revert", inputs={"actor": self.model.owner, "new_bps": 201},
            expected_revert=(boa.BoaError,), match="Cashback: invalid BPS",
        ):
            self._assert_unchanged_after_revert(
                "SP-14",
                lambda: self.protocol.cashback.set_cashback_bps(201, sender=self.model.owner),
                before,
                lambda: self.protocol.cashback.CASHBACK_BPS(),
            )

    @rule(actor_index=st.integers(0, 10))
    def unauthorized_cashback_admin_reverts(self, actor_index: int):
        """fyzz: SP-15 | Access | Nonowner Cashback configuration reverts atomically."""
        actor = self.actors[actor_index]
        if actor == self.model.owner:
            return
        before = self.protocol.cashback.CASHBACK_BPS()
        with self.diagnostics.action(
            "unauthorized_cashback_admin", inputs={"actor": actor},
            expected_revert=(boa.BoaError,), match="ownable: caller is not the owner",
        ):
            self._assert_unchanged_after_revert(
                "SP-15",
                lambda: self.protocol.cashback.set_cashback_bps(100, sender=actor),
                before,
                lambda: self.protocol.cashback.CASHBACK_BPS(),
            )

    @rule(new_owner_index=st.integers(0, 10))
    def transfer_cashback_ownership(self, new_owner_index: int):
        new_owner = self.actors[new_owner_index]
        if new_owner == self.model.owner:
            return
        with self.diagnostics.action(
            "transfer_cashback_ownership", inputs={"owner": self.model.owner, "new_owner": new_owner}
        ):
            self.protocol.cashback.transfer_ownership(new_owner, sender=self.model.owner)
            self.model.pending_owner = new_owner

    @rule()
    def accept_cashback_ownership(self):
        if self.model.pending_owner is None:
            return
        pending_owner = self.model.pending_owner
        with self.diagnostics.action(
            "accept_cashback_ownership", inputs={"pending_owner": pending_owner}
        ):
            self.protocol.cashback.accept_ownership(sender=pending_owner)
            self.model.owner = pending_owner
            self.model.pending_owner = None

    @rule(payer_index=st.integers(0, 10), merchant_index=st.integers(0, 2))
    def empty_cashback_pool_reverts_atomically(self, payer_index: int, merchant_index: int):
        """fyzz: SP-16 | Accounting | Empty rebate inventory reverts payment atomically."""
        payer = self.actors[payer_index]
        merchant = self.model.merchants[merchant_index]
        if payer == merchant or self.protocol.bobc.balanceOf(payer) < 100 * ONE:
            return
        if merchant not in self.model.approved_merchants:
            self.protocol.cashback.add_merchant(merchant, sender=self.model.owner)
            self.model.approved_merchants.add(merchant)
        self.protocol.cashback.set_cashback_bps(200, sender=self.model.owner)
        pool = self.protocol.bobc.balanceOf(self.protocol.cashback.address)
        if pool:
            self.protocol.bobc.transfer(self.model.deployer, pool, sender=self.protocol.cashback.address)
        amount = 100 * ONE
        self.protocol.bobc.approve(self.protocol.cashback.address, amount, sender=payer)
        snapshot = (
            self.protocol.bobc.balanceOf(payer),
            self.protocol.bobc.balanceOf(merchant),
            self.protocol.bobc.balanceOf(self.protocol.cashback.address),
            self.protocol.bobc.allowance(payer, self.protocol.cashback.address),
        )
        with self.diagnostics.action(
            "empty_cashback_pool_revert", inputs={"payer": payer, "merchant": merchant, "amount": amount},
            expected_revert=(boa.BoaError,), match="Cashback: empty pool",
        ):
            self._assert_unchanged_after_revert(
                "SP-16",
                lambda: self.protocol.cashback.pay(merchant, amount, sender=payer),
                snapshot,
                lambda: (
                    self.protocol.bobc.balanceOf(payer),
                    self.protocol.bobc.balanceOf(merchant),
                    self.protocol.bobc.balanceOf(self.protocol.cashback.address),
                    self.protocol.bobc.allowance(payer, self.protocol.cashback.address),
                ),
            )

    def _redeemable_exists(self) -> bool:
        for borrower in self._open_borrowers():
            pos = self._position(borrower)
            if pos[1] > pos[2] and self.protocol.engine.collateral_ratio(borrower) >= self.protocol.engine.LIQ_CR():
                return True
        return False
