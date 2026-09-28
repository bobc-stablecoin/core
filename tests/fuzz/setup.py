"""Deploy and fund a fresh local BOBC protocol for one isolated example."""
from dataclasses import dataclass

import boa
from moccasin.boa_tools import VyperContract

from src import bobc, cashback
from tests.mocks.deployers import MOCK_ERC20, MOCK_ERC4626, MOCK_PEG_ORACLE
from tests.utils.protocol import MAX_UINT256, ONE, Protocol, deploy_engine
from .model import Model


@dataclass
class Deployment:
    model: Model
    protocol: Protocol
    holders: tuple[str, ...]
    liquidators: tuple[str, ...]


def deploy(config) -> Deployment:
    del config  # Environment-specific settings are read from the selected Moccasin project.
    deployer = boa.env.generate_address("fyzz deployer")
    borrowers = tuple(boa.env.generate_address(f"fyzz borrower {i}") for i in range(3))
    holders = tuple(boa.env.generate_address(f"fyzz holder {i}") for i in range(2))
    liquidators = tuple(boa.env.generate_address(f"fyzz liquidator {i}") for i in range(2))
    merchants = tuple(boa.env.generate_address(f"fyzz merchant {i}") for i in range(3))
    reserve_provider = borrowers[2]
    merchant = merchants[0]

    with boa.env.prank(deployer):
        asset: VyperContract = MOCK_ERC20.deploy("Curve USD", "crvUSD")
        vault: VyperContract = MOCK_ERC4626.deploy(asset.address)
        oracle: VyperContract = MOCK_PEG_ORACLE.deploy(ONE)
        token: VyperContract = bobc.deploy()
        rewards: VyperContract = cashback.deploy(token.address, 100)
        engine: VyperContract = deploy_engine(token, vault, asset, oracle)
        token.bind_vault_engine(engine.address)

    for borrower in borrowers:
        asset.mint(borrower, 20_000 * ONE)
        asset.approve(engine.address, MAX_UINT256, sender=borrower)
    for holder in (*holders, *liquidators):
        asset.mint(holder, 2_000 * ONE)
    asset.mint(deployer, 2_000 * ONE)

    protocol = Protocol(
        deployer=deployer,
        user=borrowers[0],
        merchant=merchant,
        reserve_provider=reserve_provider,
        asset=asset,
        vault=vault,
        oracle=oracle,
        bobc=token,
        cashback=rewards,
        engine=engine,
    )
    model = Model(
        deployer=deployer,
        borrowers=borrowers,
        holders=holders,
        liquidators=liquidators,
        merchants=merchants,
        owner=deployer,
    )
    return Deployment(model=model, protocol=protocol, holders=holders, liquidators=liquidators)
