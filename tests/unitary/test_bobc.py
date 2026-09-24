import boa
from eth_abi import encode
from eth_keys import keys
from eth_utils import keccak

from src import bobc
from tests.conftest import ONE


def test_snekmate_metadata():
    """Snekmate exposes the locked BOBC ERC-20 metadata."""
    token = bobc.deploy()

    assert token.name() == "BOBC"
    assert token.symbol() == "BOBC"
    assert token.decimals() == 18


def test_only_bound_engine_can_mint_and_burn():
    """BOBC exposes one immutable-by-convention mint/burn authority after binding."""
    deployer = boa.env.eoa
    engine = boa.env.generate_address("engine")
    holder = boa.env.generate_address("holder")
    attacker = boa.env.generate_address("attacker")
    token = bobc.deploy()
    token.bind_vault_engine(engine, sender=deployer)

    with boa.reverts("BOBC: only engine"):
        token.mint(holder, ONE, sender=attacker)

    token.mint(holder, ONE, sender=engine)
    token.burn(holder, ONE, sender=engine)

    assert token.totalSupply() == 0


def test_eip2612_permit_sets_allowance():
    """A canonical EIP-712 signature sets allowance and consumes one nonce."""
    private_key = keys.PrivateKey(bytes.fromhex("11" * 32))
    owner = private_key.public_key.to_checksum_address()
    spender = boa.env.generate_address("spender")
    token = bobc.deploy()
    amount = 42 * ONE
    deadline = boa.env.timestamp + 3_600
    permit_typehash = keccak(
        text="Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"
    )
    struct_hash = keccak(
        encode(
            ["bytes32", "address", "address", "uint256", "uint256", "uint256"],
            [permit_typehash, owner, spender, amount, 0, deadline],
        )
    )
    digest = keccak(b"\x19\x01" + token.DOMAIN_SEPARATOR() + struct_hash)
    signature = private_key.sign_msg_hash(digest)

    token.permit(
        owner,
        spender,
        amount,
        deadline,
        signature.v + 27,
        signature.r.to_bytes(32, "big"),
        signature.s.to_bytes(32, "big"),
    )

    assert token.allowance(owner, spender) == amount
    assert token.nonces(owner) == 1
