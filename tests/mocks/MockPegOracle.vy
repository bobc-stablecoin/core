# pragma version ~=0.4.3

"""@title Mutable PegOracle test double"""


_rate: uint256


_updated_at: uint64


@deploy
def __init__(rate_: uint256):
    self._rate = rate_
    self._updated_at = convert(block.timestamp, uint64)


@external
@view
def latest() -> (uint256, uint64):
    return self._rate, self._updated_at


@external
def setRate(rate_: uint256):
    self._rate = rate_
    self._updated_at = convert(block.timestamp, uint64)


@external
def setUpdatedAt(updated_at_: uint64):
    self._updated_at = updated_at_
