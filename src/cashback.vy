# pragma version ~=0.4.3
# pragma nonreentrancy on

"""
@title BOBC Cashback
@license AGPL-3.0-or-later
@notice Pays transfers plus a rebate from finite, preminted BOBC inventory.
@dev Payouts are restricted to owner-approved merchant receivers. The contract has no BOBC mint role.
"""


# @dev We import the BOBC ERC-20 transfer and balance interface.
import interfaces.IERC20 as IERC20


# @dev We initialise Snekmate ownership and compose its two-step extension.
from snekmate.auth import ownable as ow
initializes: ow
from snekmate.auth import ownable_2step as own2
initializes: own2[ownable := ow]

exports: (
    ow.owner,
    own2.pending_owner,
    own2.transfer_ownership,
    own2.accept_ownership,
)


# @dev Basis-point denominator and operator-set hard limits.
_BPS: constant(uint256) = 10_000
MAX_CASHBACK_BPS: constant(uint256) = 200
MAX_MERCHANT_SIZE: constant(uint256) = 128


# @dev Returns the BOBC token used for payments and rebates.
BOBC: public(immutable(address))


# @dev Returns the rebate rate in basis points.
CASHBACK_BPS: public(uint256)


# @dev Approved destinations; the map is kept in sync for constant-time checks.
MERCHANTS: public(DynArray[address, MAX_MERCHANT_SIZE])
is_merchant: public(HashMap[address, bool])


# @dev Emitted after a payment and its preminted BOBC rebate complete.
event Paid:
    payer: indexed(address)
    receiver: indexed(address)
    amount: uint256
    rebate: uint256


# @dev Emitted when the rebate rate changes.
event CashbackBpsUpdated:
    previous_bps: uint256
    new_bps: uint256


# @dev Emitted whenever a merchant enters or leaves the approved set.
event MerchantAdded:
    merchant: indexed(address)

event MerchantRemoved:
    merchant: indexed(address)


@deploy
@payable
def __init__(bobc_: address, cashback_bps_: uint256):
    assert bobc_ != empty(address), "Cashback: zero BOBC"
    assert cashback_bps_ <= MAX_CASHBACK_BPS, "Cashback: invalid BPS"
    ow.__init__()
    own2.__init__()
    BOBC = bobc_
    self.CASHBACK_BPS = cashback_bps_


@external
@view
def get_merchants() -> DynArray[address, MAX_MERCHANT_SIZE]:
    """Return the complete approved merchant list."""
    return self.MERCHANTS


@external
@view
def max_cashback_bps() -> uint256:
    """Return the immutable maximum rebate rate."""
    return MAX_CASHBACK_BPS


@external
@view
def max_merchant_size() -> uint256:
    """Return the immutable maximum approved merchant count."""
    return MAX_MERCHANT_SIZE


# @dev The imported Snekmate ownership module checks the caller before every mutation.
@external
def set_cashback_bps(new_bps: uint256):
    ow._check_owner()
    assert new_bps <= MAX_CASHBACK_BPS, "Cashback: invalid BPS"
    previous_bps: uint256 = self.CASHBACK_BPS
    self.CASHBACK_BPS = new_bps
    log CashbackBpsUpdated(previous_bps=previous_bps, new_bps=new_bps)


@external
def add_merchant(merchant: address):
    ow._check_owner()
    assert merchant != empty(address), "Cashback: zero merchant"
    assert not self.is_merchant[merchant], "Cashback: duplicate merchant"
    assert len(self.MERCHANTS) < MAX_MERCHANT_SIZE, "Cashback: merchant limit"
    self.MERCHANTS.append(merchant)
    self.is_merchant[merchant] = True
    log MerchantAdded(merchant=merchant)


@external
def remove_merchant(merchant: address):
    ow._check_owner()
    assert self.is_merchant[merchant], "Cashback: merchant not found"
    index: uint256 = MAX_MERCHANT_SIZE
    merchant_count: uint256 = len(self.MERCHANTS)
    for i: uint256 in range(MAX_MERCHANT_SIZE):
        if i >= merchant_count:
            break
        if self.MERCHANTS[i] == merchant:
            index = i
            break
    assert index < MAX_MERCHANT_SIZE, "Cashback: merchant not found"
    last_index: uint256 = len(self.MERCHANTS) - 1
    if index != last_index:
        self.MERCHANTS[index] = self.MERCHANTS[last_index]
    self.MERCHANTS.pop()
    self.is_merchant[merchant] = False
    log MerchantRemoved(merchant=merchant)


@external
def clear_merchants():
    ow._check_owner()
    self._clear_merchants()


@external
def set_merchants(merchants_: DynArray[address, MAX_MERCHANT_SIZE]):
    ow._check_owner()
    self._clear_merchants()
    for merchant: address in merchants_:
        assert merchant != empty(address), "Cashback: zero merchant"
        assert not self.is_merchant[merchant], "Cashback: duplicate merchant"
        self.MERCHANTS.append(merchant)
        self.is_merchant[merchant] = True
        log MerchantAdded(merchant=merchant)


@external
def pay(receiver: address, amount: uint256) -> uint256:
    """Transfer payer BOBC to an approved merchant, then rebate the payer."""
    assert receiver != empty(address), "Cashback: zero receiver"
    assert self.is_merchant[receiver], "Cashback: unapproved merchant"
    assert receiver != msg.sender, "Cashback: self payment"
    assert amount > 0, "Cashback: zero amount"
    rebate: uint256 = amount * self.CASHBACK_BPS // _BPS
    assert rebate > 0 or self.CASHBACK_BPS == 0, "Cashback: zero rebate"
    if rebate > 0:
        assert staticcall IERC20(BOBC).balanceOf(self) >= rebate, "Cashback: empty pool"
    assert extcall IERC20(BOBC).transferFrom(msg.sender, receiver, amount), "Cashback: payment failed"
    if rebate > 0:
        assert extcall IERC20(BOBC).transfer(msg.sender, rebate), "Cashback: rebate failed"
    log Paid(payer=msg.sender, receiver=receiver, amount=amount, rebate=rebate)
    return rebate


@internal
def _clear_merchants():
    for merchant: address in self.MERCHANTS:
        self.is_merchant[merchant] = False
        log MerchantRemoved(merchant=merchant)
    self.MERCHANTS = []
