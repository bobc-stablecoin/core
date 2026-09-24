# pragma version ~=0.4.3
# pragma nonreentrancy on

"""
@title BOBC Token
@custom:contract-name bobc
@license GNU Affero General Public License v3.0 only
@notice Snekmate ERC-20 and EIP-2612 token with one VaultEngine minter and burner.
@dev The deployer binds the VaultEngine exactly once, then ownership is renounced.
"""


# @dev We import and implement the built-in ERC-20 interface.
from ethereum.ercs import IERC20
implements: IERC20


# @dev We import and implement the built-in ERC-20 metadata interface.
from ethereum.ercs import IERC20Detailed
implements: IERC20Detailed


# @dev We import and implement Snekmate's EIP-2612 permit interface.
from snekmate.tokens.interfaces import IERC20Permit
implements: IERC20Permit


# @dev We import and implement Snekmate's EIP-5267 domain interface.
from snekmate.utils.interfaces import IERC5267
implements: IERC5267


# @dev We initialise Snekmate ownership for one-time engine binding.
from snekmate.auth import ownable as ow
initializes: ow


# @dev We initialise Snekmate ERC-20 with the ownership dependency.
from snekmate.tokens import erc20
initializes: erc20[ownable := ow]


exports: (
    erc20.name,
    erc20.symbol,
    erc20.decimals,
    erc20.balanceOf,
    erc20.allowance,
    erc20.totalSupply,
    erc20.nonces,
    erc20.transfer,
    erc20.approve,
    erc20.transferFrom,
    erc20.permit,
    erc20.DOMAIN_SEPARATOR,
    erc20.eip712Domain,
)


# @dev Returns the sole address authorised to mint and burn BOBC.
vault_engine: public(address)


# @dev Emitted when the deployer irreversibly binds the VaultEngine.
event VaultEngineBound:
    vault_engine: indexed(address)


@deploy
@payable
def __init__():
    """Initialize Snekmate ERC-20 metadata, permit domain, and temporary ownership."""
    ow.__init__()
    erc20.__init__("BOBC", "BOBC", 18, "BOBC", "1")


@external
def bind_vault_engine(vault_engine_: address):
    """
    @notice Bind the only address permitted to mint or burn.
    @dev Callable once by the deployment owner. Ownership is renounced afterward.
    @param vault_engine_ The VaultEngine contract address.
    """
    ow._check_owner()
    assert self.vault_engine == empty(address), "BOBC: engine already bound"
    assert vault_engine_ != empty(address), "BOBC: zero engine"
    self.vault_engine = vault_engine_
    ow._transfer_ownership(empty(address))
    log VaultEngineBound(vault_engine=vault_engine_)


@external
def mint(receiver: address, amount: uint256):
    """
    @notice Mint BOBC to a receiver.
    @dev Only the bound VaultEngine may call.
    @param receiver The account receiving newly issued BOBC.
    @param amount The amount of BOBC to issue.
    """
    assert msg.sender == self.vault_engine, "BOBC: only engine"
    erc20._mint(receiver, amount)


@external
def burn(owner: address, amount: uint256):
    """
    @notice Burn BOBC from an account during redemption.
    @dev Only the bound VaultEngine may call; no token allowance is required.
    @param owner The account whose BOBC is destroyed.
    @param amount The amount of BOBC to destroy.
    """
    assert msg.sender == self.vault_engine, "BOBC: only engine"
    erc20._burn(owner, amount)
