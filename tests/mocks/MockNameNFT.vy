# pragma version ~=0.4.3

"""@title NameNFT balance test double"""


balanceOf: public(HashMap[address, uint256])


@external
def setBalance(owner: address, balance: uint256):
    self.balanceOf[owner] = balance
