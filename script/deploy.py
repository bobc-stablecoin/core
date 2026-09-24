import os

from moccasin.boa_tools import VyperContract
from src import bobc, cashback, vault_engine


ARBITRUM_VAULT = "0xeEaF2ccB73A01deb38Eca2947d963D64CfDe6A32"
ARBITRUM_CRVUSD = "0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def deploy() -> VyperContract:
    """Deploy and wire BOBC; reserve funding and premint remain explicit operations."""
    oracle = os.environ["PEG_ORACLE_ADDRESS"]
    name_nft = os.getenv("NAME_NFT_ADDRESS", ZERO_ADDRESS)
    require_name = _bool_env("REQUIRE_NAME")
    cashback_bps = int(os.getenv("CASHBACK_BPS", "100"))

    token = bobc.deploy()
    rewards = cashback.deploy(token.address, name_nft, cashback_bps, require_name)
    engine = vault_engine.deploy(
        token.address,
        ARBITRUM_VAULT,
        ARBITRUM_CRVUSD,
        oracle,
        int(os.getenv("BUFFER_BPS", "0")),
        int(os.getenv("MAX_TVL_ASSETS", str(1_000_000 * 10**18))),
        int(os.getenv("MAX_STALENESS", "3600")),
        int(os.getenv("MAX_DEVIATION_BPS", "500")),
        rewards.address,
        name_nft,
        require_name,
    )
    token.bind_vault_engine(engine.address)

    print(f"BOBC={token.address}")
    print(f"CASHBACK={rewards.address}")
    print(f"VAULT_ENGINE={engine.address}")
    return engine


def moccasin_main() -> VyperContract:
    return deploy()
