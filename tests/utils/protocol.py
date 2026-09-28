from dataclasses import dataclass

import boa
from moccasin.boa_tools import VyperContract

from src import bobc, cashback
from src import vault_engine as vault_engine_module
from tests.mocks.deployers import MOCK_ERC20, MOCK_ERC4626, MOCK_PEG_ORACLE


ONE = 10**18
MAX_UINT256 = 2**256 - 1
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
MIN_CR = 143 * 10**16
LIQ_CR = 120 * 10**16
MIN_DEBT = ONE
RATE_LOW = 5 * 10**15
RATE_MID = 8 * 10**16
YEAR = 365 * 24 * 60 * 60


@dataclass
class Protocol:
    deployer: str
    user: str
    merchant: str
    reserve_provider: str
    asset: VyperContract
    vault: VyperContract
    oracle: VyperContract
    bobc: VyperContract
    cashback: VyperContract
    engine: VyperContract


def _as_int(account: str) -> int:
    return int(str(account), 16)


def is_zero(account: str) -> bool:
    return _as_int(account) == 0


def same(left: str, right: str) -> bool:
    return _as_int(left) == _as_int(right)


def hints_for(engine: VyperContract, annual_rate: int, skip: str | None = None) -> tuple[str, str]:
    """Neighbors for `annual_rate`, treating `skip` as already unlinked."""
    prev = ZERO_ADDRESS
    current = engine.head()
    while not is_zero(current):
        nxt = engine.next(current)
        if skip is not None and same(current, skip):
            current = nxt
            continue
        node_rate = engine.position(current)[3]
        if node_rate <= annual_rate:
            prev = current
            current = nxt
            continue
        return prev, current
    return prev, ZERO_ADDRESS


def deploy_engine(
    token: VyperContract,
    vault: VyperContract,
    asset: VyperContract,
    oracle: VyperContract,
    *,
    min_cr: int = MIN_CR,
    liq_cr: int = LIQ_CR,
    penalty_bps: int = 500,
    max_collateral: int = 1_000_000 * ONE,
    staleness: int = 3_600,
    min_debt: int = MIN_DEBT,
    min_rate: int = RATE_LOW,
    max_rate: int = 25 * 10**16,
    value: int = 0,
) -> VyperContract:
    return vault_engine_module.deploy(
        token.address,
        vault.address,
        asset.address,
        oracle.address,
        min_cr,
        liq_cr,
        penalty_bps,
        max_collateral,
        staleness,
        min_debt,
        min_rate,
        max_rate,
        value=value,
    )


def open_position(
    engine: VyperContract,
    assets: int,
    annual_rate: int,
    sender: str,
    rate: int = ONE,
) -> int:
    """Open at the maximum debt the minimum collateral ratio allows."""
    debt = assets * rate // engine.MIN_CR()
    prev, nxt = hints_for(engine, annual_rate)
    engine.open_position(assets, debt, annual_rate, prev, nxt, sender=sender)
    return debt


def assert_books(engine: VyperContract, token: VyperContract) -> None:
    """Supply matches debt plus bad debt, and the list matches stored totals."""
    assert token.totalSupply() == engine.total_debt() + engine.bad_debt()
    assert token.balanceOf(engine.address) == engine.surplus()
    accounted = 0
    shares = 0
    current = engine.head()
    while not is_zero(current):
        pos = engine.position(current)
        accounted += pos[1]
        shares += pos[0]
        current = engine.next(current)
    assert accounted == engine.total_debt()
    assert shares == engine.total_shares()


def deploy_protocol() -> Protocol:
    deployer = boa.env.generate_address("deployer")
    user = boa.env.generate_address("borrower")
    merchant = boa.env.generate_address("merchant")
    reserve_provider = boa.env.generate_address("reserve provider")

    with boa.env.prank(deployer):
        asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
        vault = MOCK_ERC4626.deploy(asset.address)
        oracle = MOCK_PEG_ORACLE.deploy(ONE)
        token = bobc.deploy()
        rewards = cashback.deploy(token.address, 100)
        engine = deploy_engine(token, vault, asset, oracle)
        token.bind_vault_engine(engine.address)

    asset.mint(user, 10_000 * ONE)
    asset.mint(reserve_provider, 10_000 * ONE)
    asset.approve(engine.address, MAX_UINT256, sender=user)
    asset.approve(engine.address, MAX_UINT256, sender=reserve_provider)

    return Protocol(
        deployer=deployer,
        user=user,
        merchant=merchant,
        reserve_provider=reserve_provider,
        asset=asset,
        vault=vault,
        oracle=oracle,
        bobc=token,
        cashback=rewards,
        engine=engine,
    )
