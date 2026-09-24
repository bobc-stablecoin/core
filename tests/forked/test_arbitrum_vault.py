import os

import boa
import pytest

from src import bobc, vault_engine
from tests.conftest import MAX_UINT256, ONE, ZERO_ADDRESS
from tests.mocks.deployers import MOCK_ERC20, MOCK_PEG_ORACLE


VAULT = "0xeEaF2ccB73A01deb38Eca2947d963D64CfDe6A32"
CRVUSD = "0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5"


@pytest.mark.skipif(not os.getenv("ARBITRUM_RPC"), reason="ARBITRUM_RPC is not set")
def test_t12_real_vault_deposit_and_withdraw():
    """T12: use the real Arbitrum lender vault for a small mint/redeem round trip."""
    boa.fork(os.environ["ARBITRUM_RPC"])
    user = boa.env.generate_address("fork user")
    asset = MOCK_ERC20.at(CRVUSD)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = vault_engine.deploy(
        token.address, VAULT, CRVUSD, oracle.address, 0, 10_000_000 * ONE, 3_600, 500,
        ZERO_ADDRESS,
    )
    token.bind_vault_engine(engine.address)
    amount = ONE
    boa.deal(asset, user, amount)
    asset.approve(engine.address, MAX_UINT256, sender=user)

    bobc_out = engine.mint(amount, sender=user)
    assets_out = engine.redeem(bobc_out, sender=user)

    assert abs(assets_out - amount) <= 1
