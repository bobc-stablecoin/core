# pragma version ~=0.4.3

"""@title Deployment mock oracle returning a fresh 12.75 BOB per USD quote"""

RATE: constant(uint256) = 1275 * 10**16


@external
@view
def latest() -> (uint256, uint64):
    return RATE, convert(block.timestamp, uint64)
