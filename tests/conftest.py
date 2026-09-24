from dataclasses import dataclass

import boa
import pytest

from src import bobc, cashback, vault_engine
from tests.mocks.deployers import MOCK_ERC20, MOCK_ERC4626, MOCK_PEG_ORACLE


ONE = 10**18
MAX_UINT256 = 2**256 - 1
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


@dataclass
class Protocol:
    deployer: object
    user: object
    merchant: object
    reserve_provider: object
    asset: object
    vault: object
    oracle: object
    bobc: object
    cashback: object
    engine: object


@pytest.fixture
def protocol() -> Protocol:
    deployer = boa.env.generate_address("deployer")
    user = boa.env.generate_address("user")
    merchant = boa.env.generate_address("merchant")
    reserve_provider = boa.env.generate_address("reserve provider")

    with boa.env.prank(deployer):
        asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
        vault = MOCK_ERC4626.deploy(asset.address)
        oracle = MOCK_PEG_ORACLE.deploy(ONE)
        token = bobc.deploy()
        rewards = cashback.deploy(token.address, ZERO_ADDRESS, 100, False)
        engine = vault_engine.deploy(
            token.address,
            vault.address,
            asset.address,
            oracle.address,
            0,
            1_000_000 * ONE,
            3_600,
            2_000,
            rewards.address,
            ZERO_ADDRESS,
            False,
        )
        token.bind_vault_engine(engine.address)

    asset.mint(user, 10_000 * ONE)
    asset.mint(reserve_provider, 10_000 * ONE)
    asset.approve(engine.address, MAX_UINT256, sender=user)
    asset.approve(vault.address, MAX_UINT256, sender=reserve_provider)

    # Cashback premint is reserve-backed by a lender-vault deposit to the engine.
    vault.deposit(1_000 * ONE, engine.address, sender=reserve_provider)
    engine.premint_cashback(1_000 * ONE, sender=deployer)

    return Protocol(
        deployer,
        user,
        merchant,
        reserve_provider,
        asset,
        vault,
        oracle,
        token,
        rewards,
        engine,
    )
