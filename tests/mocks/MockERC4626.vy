# pragma version ~=0.4.3
# pragma nonreentrancy on

"""@title Test 1:1 ERC-4626 lender vault"""


interface IERC20:
    def balanceOf(account: address) -> uint256: view
    def transfer(receiver: address, amount: uint256) -> bool: nonpayable
    def transferFrom(owner: address, receiver: address, amount: uint256) -> bool: nonpayable


asset: public(immutable(address))


totalSupply: public(uint256)


balanceOf: public(HashMap[address, uint256])


@deploy
def __init__(asset_: address):
    asset = asset_


@external
@view
def convertToAssets(shares: uint256) -> uint256:
    if self.totalSupply == 0:
        return shares
    return shares * staticcall IERC20(asset).balanceOf(self) // self.totalSupply


@external
def deposit(assets: uint256, receiver: address) -> uint256:
    vault_assets: uint256 = staticcall IERC20(asset).balanceOf(self)
    shares: uint256 = assets
    if self.totalSupply > 0 and vault_assets > 0:
        shares = assets * self.totalSupply // vault_assets
    assert shares > 0, "Vault: zero shares"
    assert extcall IERC20(asset).transferFrom(msg.sender, self, assets), "Vault: transfer failed"
    self.totalSupply += shares
    self.balanceOf[receiver] += shares
    return shares


@external
def withdraw(assets: uint256, receiver: address, owner: address) -> uint256:
    vault_assets: uint256 = staticcall IERC20(asset).balanceOf(self)
    shares: uint256 = assets
    if self.totalSupply > 0 and vault_assets > 0:
        shares = assets * self.totalSupply // vault_assets
        if shares * vault_assets // self.totalSupply < assets:
            shares += 1
    assert owner == msg.sender, "Vault: unsupported allowance"
    assert self.balanceOf[owner] >= shares, "Vault: insufficient shares"
    self.balanceOf[owner] -= shares
    self.totalSupply -= shares
    assert extcall IERC20(asset).transfer(receiver, assets), "Vault: transfer failed"
    return shares


@external
def redeem(shares: uint256, receiver: address, owner: address) -> uint256:
    """Burn exact shares and transfer the assets they represent."""
    assert shares > 0, "Vault: zero shares"
    assert owner == msg.sender, "Vault: unsupported allowance"
    assert self.balanceOf[owner] >= shares, "Vault: insufficient shares"
    assets: uint256 = shares
    if self.totalSupply > 0:
        assets = shares * staticcall IERC20(asset).balanceOf(self) // self.totalSupply
    self.balanceOf[owner] -= shares
    self.totalSupply -= shares
    assert extcall IERC20(asset).transfer(receiver, assets), "Vault: transfer failed"
    return assets
