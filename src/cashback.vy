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


# @dev We import the optional NameNFT balance-gating interface.
import interfaces.INameNFT as INameNFT


# @dev The denominator used for basis-point calculations.
_BPS: constant(uint256) = 10_000


# @dev Returns the BOBC token used for payments and rebates.
BOBC: public(immutable(address))


# @dev Returns the optional NameNFT used to gate cashback eligibility.
NAME_NFT: public(immutable(address))


# @dev Returns the rebate rate in basis points.
CASHBACK_BPS: public(immutable(uint256))


# @dev Returns whether payers must hold at least one NameNFT.
REQUIRE_NAME: public(immutable(bool))


# @dev Emitted after a payment and its preminted BOBC rebate complete.
event Paid:
    payer: indexed(address)
    receiver: indexed(address)
    amount: uint256
    rebate: uint256


@deploy
@payable
def __init__(bobc_: address, name_nft_: address, cashback_bps_: uint256, require_name_: bool):
    assert bobc_ != empty(address), "Cashback: zero BOBC"
    assert cashback_bps_ <= _BPS, "Cashback: invalid BPS"
    assert not require_name_ or name_nft_ != empty(address), "Cashback: zero NameNFT"
    BOBC = bobc_
    NAME_NFT = name_nft_
    CASHBACK_BPS = cashback_bps_
    REQUIRE_NAME = require_name_


@external
def pay(receiver: address, amount: uint256) -> uint256:
    """Transfer payer BOBC to `receiver`, then rebate payer from finite inventory."""
    assert receiver != empty(address), "Cashback: zero receiver"
    assert amount > 0, "Cashback: zero amount"
    if REQUIRE_NAME:
        assert staticcall INameNFT(NAME_NFT).balanceOf(msg.sender) > 0, "Cashback: name required"
    rebate: uint256 = amount * CASHBACK_BPS // _BPS
    assert rebate > 0, "Cashback: zero rebate"
    assert staticcall IERC20(BOBC).balanceOf(self) >= rebate, "Cashback: empty pool"
    assert extcall IERC20(BOBC).transferFrom(msg.sender, receiver, amount), "Cashback: payment failed"
    assert extcall IERC20(BOBC).transfer(msg.sender, rebate), "Cashback: rebate failed"
    log Paid(payer=msg.sender, receiver=receiver, amount=amount, rebate=rebate)
    return rebate
