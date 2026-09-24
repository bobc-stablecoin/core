import os

import boa
import pytest

from src import bobc
from tests.conftest import ONE, RATE_LOW, deploy_engine, open_position
from tests.mocks.deployers import MOCK_ERC20, MOCK_PEG_ORACLE


VAULT = "0xeEaF2ccB73A01deb38Eca2947d963D64CfDe6A32"
CRVUSD = "0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5"


@pytest.mark.skipif(not os.getenv("ARBITRUM_RPC"), reason="ARBITRUM_RPC is not set")
def test_t12_real_vault_open_and_close():
    """Open a small position against the real Arbitrum lender vault and close it."""
    boa.fork(os.environ["ARBITRUM_RPC"])
    user = boa.env.generate_address("fork user")
    asset = MOCK_ERC20.at(CRVUSD)
    vault = type("Vault", (), {"address": VAULT})()
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = deploy_engine(token, vault, asset, oracle, min_debt=ONE, max_collateral=10_000_000 * ONE)
    token.bind_vault_engine(engine.address)
    amount = 1_000 * ONE
    boa.deal(asset, user, amount)
    asset.approve(engine.address, amount, sender=user)

    open_position(engine, amount, RATE_LOW, user)
    engine.close_position(sender=user)

    returned = asset.balanceOf(user)
    assert returned > 0
    assert returned * 1_000 >= amount * 990
    assert token.balanceOf(user) == 0
