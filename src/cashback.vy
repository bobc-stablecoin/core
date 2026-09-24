# pragma version ~=0.4.3
# pragma nonreentrancy on

"""
@title BOBC Cashback
@license AGPL-3.0-or-later
@notice Pays transfers plus a rebate from finite, preminted BOBC inventory.
@dev This contract has no BOBC mint role. An empty reward pool reverts the entire payment.
"""


# @dev We import the BOBC ERC-20 transfer and balance interface.
import interfaces.IERC20 as IERC20


# @dev The denominator used for basis-point calculations.
_BPS: constant(uint256) = 10_000


# @dev Returns the BOBC token used for payments and rebates.
BOBC: public(immutable(address))


# @dev Returns the rebate rate in basis points.
CASHBACK_BPS: public(immutable(uint256))


# @dev Emitted after a payment and its preminted BOBC rebate complete.
event Paid:
    payer: indexed(address)
    receiver: indexed(address)
    amount: uint256
    rebate: uint256


@deploy
@payable
def __init__(bobc_: address, cashback_bps_: uint256):
    assert bobc_ != empty(address), "Cashback: zero BOBC"
    assert cashback_bps_ <= _BPS, "Cashback: invalid BPS"
    BOBC = bobc_
    CASHBACK_BPS = cashback_bps_


@external
def pay(receiver: address, amount: uint256) -> uint256:
    """Transfer payer BOBC to `receiver`, then rebate payer from finite inventory."""
    assert receiver != empty(address), "Cashback: zero receiver"
    assert amount > 0, "Cashback: zero amount"
    rebate: uint256 = amount * CASHBACK_BPS // _BPS
    assert rebate > 0, "Cashback: zero rebate"
    assert staticcall IERC20(BOBC).balanceOf(self) >= rebate, "Cashback: empty pool"
    assert extcall IERC20(BOBC).transferFrom(msg.sender, receiver, amount), "Cashback: payment failed"
    assert extcall IERC20(BOBC).transfer(msg.sender, rebate), "Cashback: rebate failed"
    log Paid(payer=msg.sender, receiver=receiver, amount=amount, rebate=rebate)
    return rebate
