import boa

from script.deploy_mock import moccasin_main
from src import bobc
from tests.mocks.deployers import MOCK_DEPLOYMENT_ORACLE, MOCK_ERC20, MOCK_ERC4626
from tests.utils.protocol import ONE, ZERO_ADDRESS


def test_mock_deployment_can_open_and_close_after_staleness_window(monkeypatch, capsys):
    monkeypatch.delenv("PEG_ORACLE_ADDRESS", raising=False)
    for name in (
        "CASHBACK_BPS", "MIN_CR", "LIQ_CR", "PENALTY_BPS",
        "MAX_COLLATERAL_ASSETS", "MAX_STALENESS", "MIN_DEBT",
        "MIN_ANNUAL_RATE", "MAX_ANNUAL_RATE",
    ):
        monkeypatch.delenv(name, raising=False)

    engine = moccasin_main()
    asset = MOCK_ERC20.at(engine.ASSET())
    vault = MOCK_ERC4626.at(engine.VAULT())
    oracle = MOCK_DEPLOYMENT_ORACLE.at(engine.PEG_ORACLE())
    token = bobc.at(engine.BOBC())
    assert vault.asset() == asset.address
    output = capsys.readouterr().out
    for key in ("CRVUSD", "VAULT", "PEG_ORACLE", "BOBC", "CASHBACK", "VAULT_ENGINE"):
        assert f"{key}=" in output

    boa.env.time_travel(seconds=engine.MAX_STALENESS() + 1)
    rate, updated_at = oracle.latest()
    assert rate == 1275 * 10**16
    assert updated_at == boa.env.evm.patch.timestamp

    borrower = boa.env.eoa
    assets = 120 * ONE
    debt = 1_000 * ONE
    asset.mint(borrower, assets)
    asset.approve(engine.address, assets)
    engine.open_position(assets, debt, engine.MIN_ANNUAL_RATE(), ZERO_ADDRESS, ZERO_ADDRESS)
    assert token.balanceOf(borrower) == debt
    assert vault.balanceOf(engine.address) == assets

    engine.close_position()
    assert asset.balanceOf(borrower) == assets
    assert token.totalSupply() == 0
    assert vault.balanceOf(engine.address) == 0
