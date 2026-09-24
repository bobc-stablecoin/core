# pragma version ~=0.4.3

"""@title Test ERC-20"""


name: public(String[32])


symbol: public(String[8])


decimals: public(constant(uint8)) = 18


totalSupply: public(uint256)


balanceOf: public(HashMap[address, uint256])


allowance: public(HashMap[address, HashMap[address, uint256]])


event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256


event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256


@deploy
def __init__(name_: String[32], symbol_: String[8]):
    self.name = name_
    self.symbol = symbol_


@external
def mint(receiver: address, amount: uint256):
    self.totalSupply += amount
    self.balanceOf[receiver] += amount
    log Transfer(sender=empty(address), receiver=receiver, value=amount)


@external
def transfer(receiver: address, amount: uint256) -> bool:
    self._transfer(msg.sender, receiver, amount)
    return True


@external
def approve(spender: address, amount: uint256) -> bool:
    self.allowance[msg.sender][spender] = amount
    log Approval(owner=msg.sender, spender=spender, value=amount)
    return True


@external
def transferFrom(owner: address, receiver: address, amount: uint256) -> bool:
    allowed: uint256 = self.allowance[owner][msg.sender]
    if allowed != max_value(uint256):
        assert allowed >= amount, "ERC20: allowance"
        self.allowance[owner][msg.sender] = allowed - amount
    self._transfer(owner, receiver, amount)
    return True


@internal
def _transfer(sender: address, receiver: address, amount: uint256):
    assert self.balanceOf[sender] >= amount, "ERC20: balance"
    self.balanceOf[sender] -= amount
    self.balanceOf[receiver] += amount
    log Transfer(sender=sender, receiver=receiver, value=amount)
