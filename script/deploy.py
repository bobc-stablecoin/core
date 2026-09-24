import os

from moccasin.boa_tools import VyperContract
from src import bobc, cashback, vault_engine


ARBITRUM_VAULT = "0xeEaF2ccB73A01deb38Eca2947d963D64CfDe6A32"
ARBITRUM_CRVUSD = "0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5"
ONE = 10**18


def deploy() -> VyperContract:
    """Deploy and wire BOBC. Cashback inventory is funded by a later BOBC transfer."""
    oracle = os.environ["PEG_ORACLE_ADDRESS"]
    cashback_bps = int(os.getenv("CASHBACK_BPS", "100"))

    token = bobc.deploy()
    rewards = cashback.deploy(token.address, cashback_bps)
    engine = vault_engine.deploy(
        token.address,
        ARBITRUM_VAULT,
        ARBITRUM_CRVUSD,
        oracle,
        int(os.getenv("MIN_CR", str(143 * 10**16))),
        int(os.getenv("LIQ_CR", str(120 * 10**16))),
        int(os.getenv("PENALTY_BPS", "500")),
        int(os.getenv("MAX_COLLATERAL_ASSETS", str(1_000_000 * ONE))),
        int(os.getenv("MAX_STALENESS", "3600")),
        int(os.getenv("MIN_DEBT", str(1_000 * ONE))),
        int(os.getenv("MIN_ANNUAL_RATE", str(5 * 10**15))),
        int(os.getenv("MAX_ANNUAL_RATE", str(25 * 10**16))),
    )
    token.bind_vault_engine(engine.address)

    print(f"BOBC={token.address}")
    print(f"CASHBACK={rewards.address}")
    print(f"VAULT_ENGINE={engine.address}")
    return engine


def moccasin_main() -> VyperContract:
    return deploy()
