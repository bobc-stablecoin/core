import boa
import pytest

from src import bobc, cashback
from tests.utils.protocol import ONE, deploy_engine
from tests.mocks.deployers import MOCK_ERC20, MOCK_ERC4626, MOCK_PEG_ORACLE


@pytest.mark.parametrize("contract_name", ["BOBC", "Cashback", "VaultEngine"])
def test_production_deployments_reject_eth(contract_name):
    boa.env.set_balance(boa.env.eoa, 10)
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()

    deployers = {
        "BOBC": lambda: bobc.deploy(value=1),
        "Cashback": lambda: cashback.deploy(token.address, 100, value=1),
        "VaultEngine": lambda: deploy_engine(token, vault, asset, oracle, value=1),
    }

    with boa.reverts():
        deployers[contract_name]()
