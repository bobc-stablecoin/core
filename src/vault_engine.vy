# pragma version ~=0.4.3
# pragma nonreentrancy on

"""
@title BOBC Vault Engine
@license AGPL-3.0-or-later
@notice Collateralized debt engine: crvUSD goes to LlamaLend, BOBC is per-position debt.
@dev Interest is minted to this contract and included in debt. Supply stays equal to
     total debt plus bad debt. Closing or liquidating burns that interest from the
     engine; repayment and redemption burn principal from the caller.
"""


import interfaces.IBOBC as IBOBC


import interfaces.IERC20 as IERC20


import interfaces.IERC4626 as IERC4626


import interfaces.IPegOracle as IPegOracle


import sorted_positions
initializes: sorted_positions


# @dev The 18-decimal WAD scaling factor.
_WAD: constant(uint256) = 10**18


# @dev The denominator used for basis-point calculations.
_BPS: constant(uint256) = 10_000


# @dev The interest year, in seconds.
_YEAR: constant(uint256) = 365 * 24 * 60 * 60


# @dev The maximum number of positions one redemption may visit.
_MAX_REDEEM_STEPS: constant(uint256) = 32


# @dev Returns the BOBC token controlled by this engine.
BOBC: public(immutable(address))


# @dev Returns the Curve LlamaLend ERC-4626 lender vault.
VAULT: public(immutable(address))


# @dev Returns the crvUSD reserve asset supplied to the vault.
ASSET: public(immutable(address))


# @dev Returns the oracle providing 18-decimal BOB-per-USD rates.
PEG_ORACLE: public(immutable(address))


# @dev Returns the minimum collateral ratio, scaled by 1e18.
MIN_CR: public(immutable(uint256))


# @dev Returns the collateral ratio below which a position can be liquidated.
LIQ_CR: public(immutable(uint256))


# @dev Returns the total liquidation penalty in basis points.
PENALTY_BPS: public(immutable(uint256))


# @dev Returns the penalty share paid to the liquidator, in basis points.
LIQUIDATOR_BPS: public(immutable(uint256))


# @dev Returns the penalty share retained as crvUSD insurance, in basis points.
INSURANCE_BPS: public(immutable(uint256))


# @dev Returns the maximum crvUSD that can be supplied to the lender vault.
MAX_COLLATERAL_ASSETS: public(immutable(uint256))


# @dev Returns the maximum accepted oracle age in seconds.
MAX_STALENESS: public(immutable(uint256))


# @dev Returns the minimum BOBC debt a position may carry, aside from fee dust.
MIN_DEBT: public(immutable(uint256))


# @dev Returns the lowest accepted annual borrow rate, scaled by 1e18.
MIN_ANNUAL_RATE: public(immutable(uint256))


# @dev Returns the highest accepted annual borrow rate, scaled by 1e18.
MAX_ANNUAL_RATE: public(immutable(uint256))


struct Position:
    shares: uint256
    debt: uint256
    fees: uint256
    annual_rate: uint256
    updated_at: uint256
    exists: bool


struct Payout:
    assets_to_liquidator: uint256
    assets_to_insurance: uint256
    assets_to_borrower: uint256
    insurance_spent: uint256
    bobc_from_liquidator: uint256
    fee_burn: uint256
    bad_debt_increase: uint256


# @dev Per-borrower collateral shares and BOBC debt.
_positions: HashMap[address, Position]


# @dev Sum of stored position debt, including unpaid interest.
total_debt: public(uint256)


# @dev Sum of LlamaLend shares assigned to positions.
total_shares: public(uint256)


# @dev BOBC minted to this contract for unpaid interest.
surplus: public(uint256)


# @dev Idle crvUSD retained from liquidation penalties.
insurance_assets: public(uint256)


# @dev BOBC still circulating after collateral failed to cover a liquidation.
bad_debt: public(uint256)


# @dev Emitted when a borrower opens a position.
event Opened:
    account: indexed(address)
    assets: uint256
    debt: uint256
    annual_rate: uint256


# @dev Emitted when principal BOBC is burned and crvUSD leaves the cheapest positions.
event Redeemed:
    account: indexed(address)
    bobc_in: uint256
    assets_out: uint256


# @dev Emitted when an undercollateralized position is closed out.
event Liquidated:
    account: indexed(address)
    liquidator: indexed(address)
    debt: uint256
    assets_to_liquidator: uint256
    bad_debt_increase: uint256


@deploy
@payable
def __init__(
    bobc_: address,
    vault_: address,
    asset_: address,
    peg_oracle_: address,
    min_cr_: uint256,
    liq_cr_: uint256,
    penalty_bps_: uint256,
    max_collateral_assets_: uint256,
    max_staleness_: uint256,
    min_debt_: uint256,
    min_annual_rate_: uint256,
    max_annual_rate_: uint256,
):
    """Bind the token, vault, oracle, and risk parameters."""
    assert bobc_ != empty(address), "Engine: zero BOBC"
    assert vault_ != empty(address), "Engine: zero vault"
    assert asset_ != empty(address), "Engine: zero asset"
    assert peg_oracle_ != empty(address), "Engine: zero oracle"
    assert min_cr_ > liq_cr_, "Engine: min CR"
    assert liq_cr_ > _WAD, "Engine: liquidation CR"
    assert penalty_bps_ < _BPS, "Engine: penalty"
    assert liq_cr_ * _BPS >= _WAD * (_BPS + penalty_bps_), "Engine: penalty"
    assert max_collateral_assets_ > 0, "Engine: zero collateral cap"
    assert max_staleness_ > 0, "Engine: zero staleness"
    assert min_debt_ > 0, "Engine: zero debt floor"
    assert min_annual_rate_ > 0, "Engine: zero rate"
    assert min_annual_rate_ <= max_annual_rate_, "Engine: rate bounds"
    assert max_annual_rate_ <= _WAD, "Engine: rate bounds"
    assert staticcall IERC4626(vault_).asset() == asset_, "Engine: asset mismatch"

    BOBC = bobc_
    VAULT = vault_
    ASSET = asset_
    PEG_ORACLE = peg_oracle_
    MIN_CR = min_cr_
    LIQ_CR = liq_cr_
    PENALTY_BPS = penalty_bps_
    INSURANCE_BPS = penalty_bps_ // 5
    LIQUIDATOR_BPS = penalty_bps_ - INSURANCE_BPS
    MAX_COLLATERAL_ASSETS = max_collateral_assets_
    MAX_STALENESS = max_staleness_
    MIN_DEBT = min_debt_
    MIN_ANNUAL_RATE = min_annual_rate_
    MAX_ANNUAL_RATE = max_annual_rate_
    sorted_positions.__init__()
    assert extcall IERC20(asset_).approve(vault_, max_value(uint256)), "Engine: approve failed"


@external
def open_position(
    assets: uint256,
    debt: uint256,
    annual_rate: uint256,
    prev: address,
    next: address,
):
    """Deposit crvUSD, supply it to the lender vault, and mint BOBC debt."""
    assert not self._positions[msg.sender].exists, "Engine: position exists"
    assert assets > 0, "Engine: zero assets"
    assert debt >= MIN_DEBT, "Engine: debt floor"
    self._assert_rate(annual_rate)
    rate: uint256 = self._checked_rate()
    assert self._vault_assets() + assets <= MAX_COLLATERAL_ASSETS, "Engine: max collateral"
    shares: uint256 = self._pull_deposit(assets)
    held: uint256 = staticcall IERC4626(VAULT).convertToAssets(shares)
    assert self._ratio(held, debt, rate) >= MIN_CR, "Engine: collateral ratio"
    self._positions[msg.sender] = Position(
        shares=shares,
        debt=debt,
        fees=0,
        annual_rate=annual_rate,
        updated_at=block.timestamp,
        exists=True,
    )
    self.total_debt += debt
    sorted_positions._insert(msg.sender, annual_rate, prev, next)
    self._mint_bobc(msg.sender, debt)
    log Opened(account=msg.sender, assets=held, debt=debt, annual_rate=annual_rate)


@external
def add_collateral(assets: uint256):
    """Supply more crvUSD to the caller's position."""
    assert self._positions[msg.sender].exists, "Engine: no position"
    assert assets > 0, "Engine: zero assets"
    self._checked_rate()
    self._accrue(msg.sender)
    assert self._vault_assets() + assets <= MAX_COLLATERAL_ASSETS, "Engine: max collateral"
    shares: uint256 = self._pull_deposit(assets)
    pos: Position = self._positions[msg.sender]
    pos.shares += shares
    self._positions[msg.sender] = pos


@external
def withdraw_collateral(assets: uint256):
    """Withdraw crvUSD while the position stays at or above the minimum ratio."""
    assert assets > 0, "Engine: zero assets"
    rate: uint256 = self._checked_rate()
    self._accrue(msg.sender)
    pos: Position = self._positions[msg.sender]
    held: uint256 = staticcall IERC4626(VAULT).convertToAssets(pos.shares)
    assert assets <= held, "Engine: collateral"
    shares_burned: uint256 = extcall IERC4626(VAULT).withdraw(assets, msg.sender, self)
    assert pos.shares >= shares_burned, "Engine: shares"
    pos.shares -= shares_burned
    self.total_shares -= shares_burned
    remaining: uint256 = staticcall IERC4626(VAULT).convertToAssets(pos.shares)
    assert self._ratio(remaining, pos.debt, rate) >= MIN_CR, "Engine: collateral ratio"
    self._positions[msg.sender] = pos


@external
def borrow(amount: uint256):
    """Mint more BOBC against the caller's existing collateral at the current rate."""
    assert self._positions[msg.sender].exists, "Engine: no position"
    assert amount > 0, "Engine: zero BOBC"
    rate: uint256 = self._checked_rate()
    self._accrue(msg.sender)
    pos: Position = self._positions[msg.sender]
    pos.debt += amount
    held: uint256 = staticcall IERC4626(VAULT).convertToAssets(pos.shares)
    assert self._ratio(held, pos.debt, rate) >= MIN_CR, "Engine: collateral ratio"
    self._positions[msg.sender] = pos
    self.total_debt += amount
    self._mint_bobc(msg.sender, amount)


@external
def repay(amount: uint256):
    """Burn principal BOBC and leave at least the minimum debt outstanding."""
    assert amount > 0, "Engine: zero BOBC"
    self._checked_rate()
    self._accrue(msg.sender)
    pos: Position = self._positions[msg.sender]
    principal: uint256 = pos.debt - pos.fees
    assert amount <= principal, "Engine: exceeds principal"
    assert pos.debt - amount >= MIN_DEBT, "Engine: debt floor"
    pos.debt -= amount
    self._positions[msg.sender] = pos
    self.total_debt -= amount
    self._burn_bobc(msg.sender, amount)


@external
def close_position():
    """Burn the remaining principal, cancel engine-held interest, and return the collateral."""
    self._checked_rate()
    self._accrue(msg.sender)
    pos: Position = self._positions[msg.sender]
    principal: uint256 = pos.debt - pos.fees
    fees: uint256 = pos.fees
    shares: uint256 = pos.shares
    self._clear_position(msg.sender, pos)
    self._burn_bobc(msg.sender, principal)
    self._burn_fee(fees)
    self._redeem_all(shares, msg.sender)


@external
def set_rate(annual_rate: uint256, prev: address, next: address):
    """Accrue, then move the caller to a new place in the rate list. Hints exclude the caller."""
    self._assert_rate(annual_rate)
    self._checked_rate()
    self._accrue(msg.sender)
    pos: Position = self._positions[msg.sender]
    sorted_positions._remove(msg.sender)
    sorted_positions._insert(msg.sender, annual_rate, prev, next)
    pos.annual_rate = annual_rate
    self._positions[msg.sender] = pos


@external
def redeem(bobc_amount: uint256, max_iterations: uint256) -> uint256:
    """Burn principal BOBC and withdraw oracle crvUSD from the lowest-rate positions."""
    assert bobc_amount > 0, "Engine: zero BOBC"
    assert max_iterations > 0 and max_iterations <= _MAX_REDEEM_STEPS, "Engine: iterations"
    rate: uint256 = self._checked_rate()
    assert staticcall IERC20(BOBC).balanceOf(msg.sender) >= bobc_amount, "Engine: BOBC balance"
    remaining: uint256 = bobc_amount
    assets_out: uint256 = 0
    account: address = sorted_positions._head()
    for step: uint256 in range(_MAX_REDEEM_STEPS):
        if step >= max_iterations or remaining == 0 or account == empty(address):
            break
        nxt: address = sorted_positions._next(account)
        self._accrue(account)
        pay: uint256 = self._redeem_from(account, remaining, rate)
        if pay > 0:
            remaining -= pay
            assets_out += pay * _WAD // rate
        account = nxt
    paid: uint256 = bobc_amount - remaining
    assert paid > 0, "Engine: nothing redeemed"
    self._burn_bobc(msg.sender, paid)
    log Redeemed(account=msg.sender, bobc_in=paid, assets_out=assets_out)
    return assets_out


@external
def liquidate(account: address):
    """Seize a position below the liquidation ratio and pay the caller for the debt they burn."""
    assert account != empty(address), "Engine: zero account"
    assert self._positions[account].exists, "Engine: no position"
    rate: uint256 = self._checked_rate()
    self._accrue(account)
    pos: Position = self._positions[account]
    assets: uint256 = staticcall IERC4626(VAULT).convertToAssets(pos.shares)
    assert self._ratio(assets, pos.debt, rate) < LIQ_CR, "Engine: healthy"
    payout: Payout = self._payout(assets, pos.debt, pos.fees, rate)
    shares: uint256 = pos.shares
    debt: uint256 = pos.debt
    self._clear_position(account, pos)
    self.insurance_assets = self.insurance_assets - payout.insurance_spent + payout.assets_to_insurance
    self.bad_debt += payout.bad_debt_increase
    self._burn_bobc(msg.sender, payout.bobc_from_liquidator)
    self._burn_fee(payout.fee_burn)
    if shares > 0:
        self._redeem_all(shares, self)
    if payout.assets_to_liquidator > 0:
        assert extcall IERC20(ASSET).transfer(msg.sender, payout.assets_to_liquidator), "Engine: transfer failed"
    if payout.assets_to_borrower > 0:
        assert extcall IERC20(ASSET).transfer(account, payout.assets_to_borrower), "Engine: transfer failed"
    log Liquidated(
        account=account,
        liquidator=msg.sender,
        debt=debt,
        assets_to_liquidator=payout.assets_to_liquidator,
        bad_debt_increase=payout.bad_debt_increase,
    )


@external
@view
def position(account: address) -> Position:
    """Return the stored position. Debt does not include interest since the last touch."""
    return self._positions[account]


@external
@view
def collateral_assets(account: address) -> uint256:
    """Return the crvUSD represented by this position's lender-vault shares."""
    return staticcall IERC4626(VAULT).convertToAssets(self._positions[account].shares)


@external
@view
def pending_interest(account: address) -> uint256:
    """Return BOBC interest accrued since the position was last touched."""
    pos: Position = self._positions[account]
    if not pos.exists:
        return 0
    return self._pending(pos.debt, pos.annual_rate, pos.updated_at)


@external
@view
def collateral_ratio(account: address) -> uint256:
    """Return the post-interest collateral ratio, scaled by 1e18."""
    pos: Position = self._positions[account]
    assert pos.exists, "Engine: no position"
    rate: uint256 = self._checked_rate()
    debt: uint256 = pos.debt + self._pending(pos.debt, pos.annual_rate, pos.updated_at)
    assets: uint256 = staticcall IERC4626(VAULT).convertToAssets(pos.shares)
    return self._ratio(assets, debt, rate)


@external
@view
def head() -> address:
    """Return the lowest-rate open position."""
    return sorted_positions._head()


@external
@view
def next(account: address) -> address:
    """Return the next position in ascending rate order."""
    return sorted_positions._next(account)


@internal
def _redeem_from(account: address, remaining: uint256, rate: uint256) -> uint256:
    """Withdraw oracle crvUSD for as much principal as this position can give up."""
    pos: Position = self._positions[account]
    assets: uint256 = staticcall IERC4626(VAULT).convertToAssets(pos.shares)
    if self._ratio(assets, pos.debt, rate) < LIQ_CR:
        return 0
    principal: uint256 = pos.debt - pos.fees
    if principal == 0:
        return 0
    affordable: uint256 = assets * rate // _WAD
    if affordable < principal:
        principal = affordable
    if principal == 0:
        return 0
    pay: uint256 = self._bounded_redemption(pos.debt, pos.fees, principal, remaining)
    if pay == 0:
        return 0
    pay_assets: uint256 = pay * _WAD // rate
    if pay_assets == 0 or pay_assets > assets:
        return 0
    shares_burned: uint256 = extcall IERC4626(VAULT).withdraw(pay_assets, msg.sender, self)
    assert pos.shares >= shares_burned, "Engine: shares"
    pos.shares -= shares_burned
    self.total_shares -= shares_burned
    pos.debt -= pay
    self.total_debt -= pay
    if pos.debt == pos.fees:
        # The last principal was redeemed. Retire the fee-only node and burn
        # its accrued BOBC from surplus so it cannot block later redemptions.
        fee_debt: uint256 = pos.fees
        remaining_shares: uint256 = pos.shares
        self._clear_position(account, pos)
        self._burn_fee(fee_debt)
        self._redeem_all(remaining_shares, account)
    else:
        assert pos.shares > 0, "Engine: empty collateral"
        self._positions[account] = pos
    return pay


@internal
@view
def _bounded_redemption(debt: uint256, fees: uint256, principal: uint256, remaining: uint256) -> uint256:
    """Take principal without leaving a non-fee remainder under the debt floor."""
    pay: uint256 = remaining
    if pay > principal:
        pay = principal
    remainder: uint256 = debt - pay
    if remainder == 0 or remainder >= MIN_DEBT:
        return pay
    full_principal: uint256 = debt - fees
    if full_principal > principal:
        full_principal = principal
    if remaining >= full_principal:
        return full_principal
    if debt <= MIN_DEBT:
        return 0
    room: uint256 = debt - MIN_DEBT
    if room > principal:
        room = principal
    if remaining < room:
        room = remaining
    if room == 0 or debt - room < MIN_DEBT:
        return 0
    return room


@internal
@view
def _payout(assets: uint256, debt: uint256, fees: uint256, rate: uint256) -> Payout:
    """Split a liquidation between the caller, insurance, the borrower, and bad debt."""
    debt_assets: uint256 = debt * _WAD // rate
    principal: uint256 = debt - fees
    if assets >= debt_assets:
        to_liquidator: uint256 = debt_assets * (_BPS + LIQUIDATOR_BPS) // _BPS
        if to_liquidator > assets:
            to_liquidator = assets
        to_insurance: uint256 = debt_assets * INSURANCE_BPS // _BPS
        if to_liquidator + to_insurance > assets:
            if assets > to_liquidator:
                to_insurance = assets - to_liquidator
            else:
                to_insurance = 0
        return Payout(
            assets_to_liquidator=to_liquidator,
            assets_to_insurance=to_insurance,
            assets_to_borrower=assets - to_liquidator - to_insurance,
            insurance_spent=0,
            bobc_from_liquidator=principal,
            fee_burn=fees,
            bad_debt_increase=0,
        )
    cover: uint256 = self.insurance_assets
    shortfall: uint256 = debt_assets - assets
    if cover > shortfall:
        cover = shortfall
    pot: uint256 = assets + cover
    bobc_value: uint256 = pot * rate // _WAD
    if bobc_value > debt:
        bobc_value = debt
    from_liquidator: uint256 = bobc_value
    fee_burn: uint256 = 0
    if from_liquidator > principal:
        fee_burn = from_liquidator - principal
        if fee_burn > fees:
            fee_burn = fees
        from_liquidator = bobc_value - fee_burn
    return Payout(
        assets_to_liquidator=pot,
        assets_to_insurance=0,
        assets_to_borrower=0,
        insurance_spent=cover,
        bobc_from_liquidator=from_liquidator,
        fee_burn=fee_burn,
        bad_debt_increase=debt - from_liquidator - fee_burn,
    )


@internal
def _accrue(account: address):
    """Mint interest to this contract and add it to the position's debt."""
    pos: Position = self._positions[account]
    assert pos.exists, "Engine: no position"
    interest: uint256 = self._pending(pos.debt, pos.annual_rate, pos.updated_at)
    pos.updated_at = block.timestamp
    if interest == 0:
        self._positions[account] = pos
        return
    pos.debt += interest
    pos.fees += interest
    self._positions[account] = pos
    self.total_debt += interest
    self.surplus += interest
    self._mint_bobc(self, interest)


@internal
def _clear_position(account: address, pos: Position):
    """Unlink a position and drop its stored debt. Shares are redeemed by the caller."""
    sorted_positions._remove(account)
    self.total_debt -= pos.debt
    self._positions[account] = self._zero_position()


@internal
def _pull_deposit(assets: uint256) -> uint256:
    """Move crvUSD from the caller into the lender vault and count the new shares."""
    assert extcall IERC20(ASSET).transferFrom(msg.sender, self, assets), "Engine: transfer failed"
    shares: uint256 = extcall IERC4626(VAULT).deposit(assets, self)
    self.total_shares += shares
    return shares


@internal
def _redeem_all(shares: uint256, receiver: address) -> uint256:
    """Redeem the caller's counted shares. A zero balance is a no-op."""
    if shares == 0:
        return 0
    self.total_shares -= shares
    return extcall IERC4626(VAULT).redeem(shares, receiver, self)


@internal
def _mint_bobc(receiver: address, amount: uint256):
    """Mint BOBC when the amount is non-zero."""
    if amount == 0:
        return
    extcall IBOBC(BOBC).mint(receiver, amount)


@internal
def _burn_bobc(owner: address, amount: uint256):
    """Burn BOBC when the amount is non-zero."""
    if amount == 0:
        return
    extcall IBOBC(BOBC).burn(owner, amount)


@internal
def _burn_fee(amount: uint256):
    """Burn interest BOBC held by this contract."""
    if amount == 0:
        return
    assert self.surplus >= amount, "Engine: surplus"
    self.surplus -= amount
    self._burn_bobc(self, amount)


@internal
@view
def _pending(debt: uint256, annual_rate: uint256, updated_at: uint256) -> uint256:
    """Return interest owed for `debt` since `updated_at`."""
    if debt == 0 or block.timestamp <= updated_at:
        return 0
    elapsed: uint256 = block.timestamp - updated_at
    return debt * annual_rate // _WAD * elapsed // _YEAR


@internal
@view
def _ratio(assets: uint256, debt: uint256, rate: uint256) -> uint256:
    """Return collateral value divided by debt, scaled by 1e18."""
    if debt == 0:
        return max_value(uint256)
    value: uint256 = assets * rate // _WAD
    return value * _WAD // debt


@internal
@view
def _vault_assets() -> uint256:
    """Return crvUSD represented by shares assigned to positions."""
    if self.total_shares == 0:
        return 0
    return staticcall IERC4626(VAULT).convertToAssets(self.total_shares)


@internal
@view
def _checked_rate() -> uint256:
    """Return the oracle rate after rejecting a zero, future, or stale sample."""
    rate: uint256 = 0
    updated_at: uint64 = 0
    rate, updated_at = staticcall IPegOracle(PEG_ORACLE).latest()
    assert rate > 0, "Engine: zero rate"
    assert convert(updated_at, uint256) <= block.timestamp, "Engine: future oracle"
    assert block.timestamp - convert(updated_at, uint256) <= MAX_STALENESS, "Engine: stale oracle"
    return rate


@internal
@view
def _assert_rate(annual_rate: uint256):
    """Revert unless the annual rate is inside the configured bounds."""
    assert annual_rate >= MIN_ANNUAL_RATE, "Engine: rate bounds"
    assert annual_rate <= MAX_ANNUAL_RATE, "Engine: rate bounds"


@internal
@pure
def _zero_position() -> Position:
    """Return an empty position record."""
    return Position(shares=0, debt=0, fees=0, annual_rate=0, updated_at=0, exists=False)
