import os
from pathlib import Path

import boa

from moccasin.boa_tools import VyperContract
from src import bobc, cashback, vault_engine


MOCKS_DIR = Path(__file__).resolve().parents[1] / "tests" / "mocks"
WAD = 10**18


def deploy() -> VyperContract:
    """Deploy and wire BOBC with mock crvUSD, a lender vault, and a fresh peg oracle."""
    asset = boa.load_partial(str(MOCKS_DIR / "MockERC20.vy")).deploy("Mock Curve USD", "crvUSD")
    vault = boa.load_partial(str(MOCKS_DIR / "MockERC4626.vy")).deploy(asset.address)
    oracle = boa.load_partial(str(MOCKS_DIR / "MockDeploymentOracle.vy")).deploy()
    cashback_bps = int(os.getenv("CASHBACK_BPS", "100"))

    token = bobc.deploy()
    rewards = cashback.deploy(token.address, cashback_bps)
    engine = vault_engine.deploy(
        token.address,
        vault.address,
        asset.address,
        oracle.address,
        int(os.getenv("MIN_CR", str(143 * 10**16))),
        int(os.getenv("LIQ_CR", str(120 * 10**16))),
        int(os.getenv("PENALTY_BPS", "500")),
        int(os.getenv("MAX_COLLATERAL_ASSETS", str(1_000_000 * WAD))),
        int(os.getenv("MAX_STALENESS", "3600")),
        int(os.getenv("MIN_DEBT", str(1_000 * WAD))),
        int(os.getenv("MIN_ANNUAL_RATE", str(5 * 10**15))),
        int(os.getenv("MAX_ANNUAL_RATE", str(25 * 10**16))),
    )
    token.bind_vault_engine(engine.address)

    print(f"CRVUSD={asset.address}")
    print(f"VAULT={vault.address}")
    print(f"PEG_ORACLE={oracle.address}")
    print(f"BOBC={token.address}")
    print(f"CASHBACK={rewards.address}")
    print(f"VAULT_ENGINE={engine.address}")
    return engine


def moccasin_main() -> VyperContract:
    return deploy()
