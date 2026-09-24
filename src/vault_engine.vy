# pragma version ~=0.4.3
# pragma nonreentrancy on

"""
@title BOBC Vault Engine
@license AGPL-3.0-or-later
@notice Supplies crvUSD into an ERC-4626 lender vault and mints/redeems fully reserved BOBC.
@dev This is a reserve vault, not a CDP. It has no borrower positions or liquidation path.
"""


# @dev We import the BOBC mint, burn, and supply interface.
import interfaces.IBOBC as IBOBC


# @dev We import the reserve asset ERC-20 interface.
import interfaces.IERC20 as IERC20


# @dev We import the lender-vault ERC-4626 interface.
import interfaces.IERC4626 as IERC4626


# @dev We import the external BOB-per-USD rate interface.
import interfaces.IPegOracle as IPegOracle


# @dev The 18-decimal WAD scaling factor.
_WAD: constant(uint256) = 10**18


# @dev The denominator used for basis-point calculations.
_BPS: constant(uint256) = 10_000


# @dev Returns the BOBC token controlled by this engine.
BOBC: public(immutable(address))


# @dev Returns the Curve LlamaLend ERC-4626 lender vault.
VAULT: public(immutable(address))


# @dev Returns the crvUSD reserve asset supplied to the vault.
ASSET: public(immutable(address))


# @dev Returns the oracle providing 18-decimal BOB-per-USD rates.
PEG_ORACLE: public(immutable(address))


# @dev Returns the reserve-value haircut in basis points.
BUFFER_BPS: public(immutable(uint256))


# @dev Returns the maximum permitted reserves denominated in crvUSD.
MAX_TVL_ASSETS: public(immutable(uint256))


# @dev Returns the maximum accepted oracle age in seconds.
MAX_STALENESS: public(immutable(uint256))


# @dev Returns the maximum rate deviation from 1e18 in basis points.
MAX_DEVIATION_BPS: public(immutable(uint256))


# @dev Returns the optional cashback inventory contract.
CASHBACK: public(immutable(address))


# @dev Returns the deployment owner authorised for the one-time premint.
owner: public(address)


# @dev Returns whether the finite cashback inventory has been preminted.
cashback_preminted: public(bool)


# @dev Emitted after reserve assets are supplied and BOBC is minted.
event Minted:
    account: indexed(address)
    assets: uint256
    bobc_out: uint256


# @dev Emitted after BOBC is burned and reserve assets are withdrawn.
event Redeemed:
    account: indexed(address)
    bobc_amount: uint256
    assets_out: uint256


# @dev Emitted when the one-time, reserve-backed cashback supply is minted.
event CashbackPreminted:
    amount: uint256


@deploy
@payable
def __init__(
    bobc_: address,
    vault_: address,
    asset_: address,
    peg_oracle_: address,
    buffer_bps_: uint256,
    max_tvl_assets_: uint256,
    max_staleness_: uint256,
    max_deviation_bps_: uint256,
    cashback_: address,
):
    assert bobc_ != empty(address), "Engine: zero BOBC"
    assert vault_ != empty(address), "Engine: zero vault"
    assert asset_ != empty(address), "Engine: zero asset"
    assert peg_oracle_ != empty(address), "Engine: zero oracle"
    assert buffer_bps_ < _BPS, "Engine: invalid buffer"
    assert max_tvl_assets_ > 0, "Engine: zero TVL cap"
    assert max_staleness_ > 0, "Engine: zero staleness"
    assert max_deviation_bps_ <= _BPS, "Engine: invalid deviation"
    assert staticcall IERC4626(vault_).asset() == asset_, "Engine: asset mismatch"

    BOBC = bobc_
    VAULT = vault_
    ASSET = asset_
    PEG_ORACLE = peg_oracle_
    BUFFER_BPS = buffer_bps_
    MAX_TVL_ASSETS = max_tvl_assets_
    MAX_STALENESS = max_staleness_
    MAX_DEVIATION_BPS = max_deviation_bps_
    CASHBACK = cashback_
    self.owner = msg.sender

    assert extcall IERC20(asset_).approve(vault_, max_value(uint256)), "Engine: approve failed"


@external
def mint(assets: uint256) -> uint256:
    """Deposit crvUSD, supply it to the lender vault, and mint BOBC at the oracle rate."""
    assert assets > 0, "Engine: zero assets"
    rate: uint256 = self._checked_rate()
    assert self._reserve_assets() + assets <= MAX_TVL_ASSETS, "Engine: max TVL"
    assert extcall IERC20(ASSET).transferFrom(msg.sender, self, assets), "Engine: transfer failed"
    extcall IERC4626(VAULT).deposit(assets, self)
    bobc_out: uint256 = assets * rate // _WAD
    assert bobc_out > 0, "Engine: zero BOBC"
    extcall IBOBC(BOBC).mint(msg.sender, bobc_out)
    self._assert_solvent(rate)
    log Minted(account=msg.sender, assets=assets, bobc_out=bobc_out)
    return bobc_out


@external
def redeem(bobc_amount: uint256) -> uint256:
    """Burn BOBC and withdraw the oracle-equivalent amount of crvUSD."""
    assert bobc_amount > 0, "Engine: zero BOBC"
    rate: uint256 = self._checked_rate()
    assets_out: uint256 = bobc_amount * _WAD // rate
    assert assets_out > 0, "Engine: zero assets"
    extcall IBOBC(BOBC).burn(msg.sender, bobc_amount)
    extcall IERC4626(VAULT).withdraw(assets_out, msg.sender, self)
    self._assert_solvent(rate)
    log Redeemed(account=msg.sender, bobc_amount=bobc_amount, assets_out=assets_out)
    return assets_out


@external
def premint_cashback(amount: uint256):
    """Mint the one-time cashback inventory, backed by existing reserve surplus."""
    assert msg.sender == self.owner, "Engine: only owner"
    assert CASHBACK != empty(address), "Engine: cashback disabled"
    assert not self.cashback_preminted, "Engine: cashback already preminted"
    assert amount > 0, "Engine: zero amount"
    rate: uint256 = self._checked_rate()
    self.cashback_preminted = True
    extcall IBOBC(BOBC).mint(CASHBACK, amount)
    self._assert_solvent(rate)
    log CashbackPreminted(amount=amount)


@external
@view
def reserve_assets() -> uint256:
    """Return crvUSD represented by this engine's lender-vault shares."""
    return self._reserve_assets()


@external
@view
def current_rate() -> uint256:
    """Return the current rate after freshness and deviation checks."""
    return self._checked_rate()


@external
@view
def max_mintable() -> uint256:
    """Return current haircut-adjusted BOBC reserve value not already issued."""
    rate: uint256 = self._checked_rate()
    capacity: uint256 = self._backing_value(rate)
    supply: uint256 = staticcall IBOBC(BOBC).totalSupply()
    if capacity <= supply:
        return 0
    return capacity - supply


@external
@view
def collateral_ratio() -> uint256:
    """Return gross reserve value divided by BOBC supply, scaled by 1e18."""
    supply: uint256 = staticcall IBOBC(BOBC).totalSupply()
    if supply == 0:
        return max_value(uint256)
    gross_value: uint256 = self._reserve_assets() * self._checked_rate() // _WAD
    return gross_value * _WAD // supply


@internal
@view
def _checked_rate() -> uint256:
    rate: uint256 = 0
    updated_at: uint64 = 0
    rate, updated_at = staticcall IPegOracle(PEG_ORACLE).latest()
    assert rate > 0, "Engine: zero rate"
    assert convert(updated_at, uint256) <= block.timestamp, "Engine: future oracle"
    assert block.timestamp - convert(updated_at, uint256) <= MAX_STALENESS, "Engine: stale oracle"
    deviation: uint256 = 0
    if rate >= _WAD:
        deviation = rate - _WAD
    else:
        deviation = _WAD - rate
    assert deviation * _BPS <= _WAD * MAX_DEVIATION_BPS, "Engine: rate deviation"
    return rate


@internal
@view
def _reserve_assets() -> uint256:
    shares: uint256 = staticcall IERC4626(VAULT).balanceOf(self)
    return staticcall IERC4626(VAULT).convertToAssets(shares)


@internal
@view
def _backing_value(rate: uint256) -> uint256:
    gross_value: uint256 = self._reserve_assets() * rate // _WAD
    return gross_value * (_BPS - BUFFER_BPS) // _BPS


@internal
@view
def _assert_solvent(rate: uint256):
    assert self._backing_value(rate) >= staticcall IBOBC(BOBC).totalSupply(), "Engine: insolvent"
