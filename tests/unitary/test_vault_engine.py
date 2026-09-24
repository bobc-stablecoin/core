import boa

from src import bobc, vault_engine
from tests.conftest import MAX_UINT256, ONE, ZERO_ADDRESS
from tests.mocks.deployers import MOCK_ERC20, MOCK_ERC4626, MOCK_PEG_ORACLE


def test_t1_mint_at_rate(protocol):
    """T1: crvUSD enters the vault and BOBC is issued at rate R."""
    assets = 100 * ONE
    rate = 1_050_000_000_000_000_000
    protocol.oracle.setRate(rate)

    bobc_out = protocol.engine.mint(assets, sender=protocol.user)

    assert bobc_out == assets * rate // ONE
    assert protocol.bobc.balanceOf(protocol.user) == bobc_out
    assert protocol.engine.reserve_assets() == 1_000 * ONE + assets


def test_t2_redeem_round_trip_within_tolerance(protocol):
    """T2: mint then redeem returns the original crvUSD within integer tolerance."""
    assets = 123 * ONE + 17
    starting_balance = protocol.asset.balanceOf(protocol.user)
    bobc_out = protocol.engine.mint(assets, sender=protocol.user)

    assets_out = protocol.engine.redeem(bobc_out, sender=protocol.user)

    assert abs(assets_out - assets) <= 1
    assert abs(protocol.asset.balanceOf(protocol.user) - starting_balance) <= 1
    assert protocol.bobc.balanceOf(protocol.user) == 0


def test_t3_stale_oracle_blocks_mint_and_redeem(protocol):
    """T3: both clearing directions stop when the oracle is stale."""
    protocol.engine.mint(10 * ONE, sender=protocol.user)
    _, updated_at = protocol.oracle.latest()
    boa.env.time_travel(seconds=3_601)

    with boa.reverts("Engine: stale oracle"):
        protocol.engine.mint(ONE, sender=protocol.user)
    with boa.reverts("Engine: stale oracle"):
        protocol.engine.redeem(ONE, sender=protocol.user)

    assert updated_at < boa.env.timestamp


def test_t4_deviation_blocks_mint_and_redeem(protocol):
    """T4: a rate outside the configured band pauses both directions."""
    protocol.engine.mint(10 * ONE, sender=protocol.user)
    protocol.oracle.setRate(1_210_000_000_000_000_000)

    with boa.reverts("Engine: rate deviation"):
        protocol.engine.mint(ONE, sender=protocol.user)
    with boa.reverts("Engine: rate deviation"):
        protocol.engine.redeem(ONE, sender=protocol.user)


def test_t5_max_tvl_blocks_mint():
    """T5: deposits cannot take lender-vault reserves above MAX_TVL_ASSETS."""
    account = boa.env.generate_address("account")
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = vault_engine.deploy(
        token.address, vault.address, asset.address, oracle.address, 0, 100 * ONE, 3_600, 500,
        ZERO_ADDRESS,
    )
    token.bind_vault_engine(engine.address)
    asset.mint(account, 101 * ONE)
    asset.approve(engine.address, MAX_UINT256, sender=account)

    with boa.reverts("Engine: max TVL"):
        engine.mint(101 * ONE, sender=account)


def test_t6_buffer_requires_reserve_surplus():
    """T6: buffer haircut rejects unbuffered issuance and accepts prefunded surplus."""
    deployer = boa.env.eoa
    account = boa.env.generate_address("account")
    reserve_provider = boa.env.generate_address("reserve provider")
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = vault_engine.deploy(
        token.address, vault.address, asset.address, oracle.address, 100, 1_000 * ONE, 3_600, 500,
        ZERO_ADDRESS,
    )
    token.bind_vault_engine(engine.address, sender=deployer)
    asset.mint(account, 200 * ONE)
    asset.mint(reserve_provider, 10 * ONE)
    asset.approve(engine.address, MAX_UINT256, sender=account)
    asset.approve(vault.address, MAX_UINT256, sender=reserve_provider)

    with boa.reverts("Engine: insolvent"):
        engine.mint(100 * ONE, sender=account)

    vault.deposit(2 * ONE, engine.address, sender=reserve_provider)
    engine.mint(100 * ONE, sender=account)

    assert engine.collateral_ratio() >= 102 * ONE // 100
