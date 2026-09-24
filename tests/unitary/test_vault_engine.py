import boa

from src import bobc
from tests.conftest import (
    MAX_UINT256,
    MIN_CR,
    ONE,
    RATE_LOW,
    RATE_MID,
    YEAR,
    ZERO_ADDRESS,
    assert_books,
    deploy_engine,
    hints_for,
    open_position,
)
from tests.mocks.deployers import MOCK_ERC20, MOCK_ERC4626, MOCK_PEG_ORACLE


def test_open_issues_debt_at_minimum_ratio(protocol):
    """A full borrow mints assets * rate / MIN_CR."""
    assets = 1_430 * ONE
    debt = open_position(protocol.engine, assets, RATE_LOW, protocol.user)

    assert debt == assets * ONE // MIN_CR
    assert protocol.bobc.balanceOf(protocol.user) == debt
    assert protocol.engine.collateral_assets(protocol.user) == assets
    assert protocol.engine.collateral_ratio(protocol.user) >= MIN_CR
    assert_books(protocol.engine, protocol.bobc)


def test_close_returns_collateral(protocol):
    """Closing with no time elapsed returns the deposited crvUSD."""
    assets = 1_430 * ONE
    starting = protocol.asset.balanceOf(protocol.user)
    open_position(protocol.engine, assets, RATE_LOW, protocol.user)

    protocol.engine.close_position(sender=protocol.user)

    assert protocol.asset.balanceOf(protocol.user) == starting
    assert protocol.bobc.balanceOf(protocol.user) == 0
    assert protocol.engine.head() == ZERO_ADDRESS
    assert_books(protocol.engine, protocol.bobc)


def test_interest_mints_matching_surplus_and_close_clears_it(protocol):
    """A year of interest grows debt and the engine balance by the same amount."""
    assets = 1_430 * ONE
    annual_rate = 10**17
    starting = protocol.asset.balanceOf(protocol.user)
    debt = open_position(protocol.engine, assets, annual_rate, protocol.user)
    boa.env.time_travel(seconds=YEAR)
    protocol.oracle.setUpdatedAt(boa.env.timestamp)
    prev, nxt = hints_for(protocol.engine, annual_rate, skip=protocol.user)

    protocol.engine.set_rate(annual_rate, prev, nxt, sender=protocol.user)

    interest = debt * annual_rate // ONE
    assert protocol.engine.position(protocol.user)[1] == debt + interest
    assert protocol.engine.surplus() == interest
    assert protocol.bobc.balanceOf(protocol.engine.address) == interest
    assert_books(protocol.engine, protocol.bobc)

    protocol.engine.close_position(sender=protocol.user)

    assert protocol.engine.surplus() == 0
    assert protocol.asset.balanceOf(protocol.user) == starting
    assert_books(protocol.engine, protocol.bobc)


def test_yield_withdraw_stops_on_the_minimum_ratio(protocol):
    """LlamaLend yield can be withdrawn above MIN_CR and not through it."""
    assets = 1_430 * ONE
    debt = open_position(protocol.engine, assets, RATE_LOW, protocol.user)
    protocol.asset.mint(protocol.vault.address, 200 * ONE)
    held = protocol.engine.collateral_assets(protocol.user)
    minimum = debt * MIN_CR // ONE
    excess = held - minimum

    protocol.engine.withdraw_collateral(10 * ONE, sender=protocol.user)
    with boa.reverts("Engine: collateral ratio"):
        protocol.engine.withdraw_collateral(excess, sender=protocol.user)

    assert protocol.engine.collateral_ratio(protocol.user) >= MIN_CR
    assert_books(protocol.engine, protocol.bobc)


def test_rate_move_liquidates_only_below_the_line(protocol):
    """A stronger BOB lowers one position's ratio and does not freeze a healthy one."""
    assets = 1_430 * ONE
    open_position(protocol.engine, assets, RATE_LOW, protocol.user)
    protocol.oracle.setRate(95 * 10**16)

    with boa.reverts("Engine: healthy"):
        protocol.engine.liquidate(protocol.user, sender=protocol.merchant)
    protocol.engine.add_collateral(ONE, sender=protocol.user)

    protocol.oracle.setRate(80 * 10**16)
    debt = protocol.engine.position(protocol.user)[1]
    protocol.bobc.transfer(protocol.merchant, debt, sender=protocol.user)
    before = protocol.asset.balanceOf(protocol.merchant)

    protocol.engine.liquidate(protocol.user, sender=protocol.merchant)

    assert not protocol.engine.position(protocol.user)[5]
    assert protocol.engine.insurance_assets() > 0
    assert protocol.asset.balanceOf(protocol.merchant) > before
    assert_books(protocol.engine, protocol.bobc)


def test_profitable_liquidation_splits_the_penalty(protocol):
    """The caller receives the 4% slice and the engine retains the 1% slice."""
    assets = 1_430 * ONE
    open_position(protocol.engine, assets, RATE_LOW, protocol.user)
    protocol.oracle.setRate(80 * 10**16)
    debt = protocol.engine.position(protocol.user)[1]
    rate = 80 * 10**16
    debt_assets = debt * ONE // rate
    protocol.bobc.transfer(protocol.merchant, debt, sender=protocol.user)
    borrower_before = protocol.asset.balanceOf(protocol.user)

    protocol.engine.liquidate(protocol.user, sender=protocol.merchant)

    assert protocol.asset.balanceOf(protocol.merchant) == debt_assets * 10_400 // 10_000
    assert protocol.engine.insurance_assets() == debt_assets * 100 // 10_000
    returned = debt_assets * 100 // 10_000
    assert protocol.asset.balanceOf(protocol.user) == borrower_before + assets - (
        debt_assets * 10_400 // 10_000 + returned
    )
    assert_books(protocol.engine, protocol.bobc)


def test_underwater_liquidation_records_bad_debt_after_insurance(protocol):
    """Insurance crvUSD is spent before the uncovered BOBC is recorded as bad debt."""
    assets = 1_430 * ONE
    open_position(protocol.engine, assets, RATE_LOW, protocol.user)
    protocol.oracle.setRate(80 * 10**16)
    debt = protocol.engine.position(protocol.user)[1]
    protocol.bobc.transfer(protocol.merchant, debt, sender=protocol.user)
    protocol.engine.liquidate(protocol.user, sender=protocol.merchant)
    insurance = protocol.engine.insurance_assets()

    bob_assets = 1_430 * ONE
    bob_debt = open_position(
        protocol.engine, bob_assets, RATE_MID, protocol.reserve_provider, rate=80 * 10**16
    )
    protocol.oracle.setRate(40 * 10**16)
    cover = insurance
    pot = bob_assets + cover
    bobc_paid = pot * 40 * 10**16 // ONE
    protocol.bobc.transfer(protocol.merchant, bob_debt, sender=protocol.reserve_provider)

    protocol.engine.liquidate(protocol.reserve_provider, sender=protocol.merchant)

    assert protocol.engine.insurance_assets() == 0
    assert protocol.engine.bad_debt() == bob_debt - bobc_paid
    assert protocol.asset.balanceOf(protocol.merchant) > 0
    assert_books(protocol.engine, protocol.bobc)


def test_stale_oracle_blocks_state_changes(protocol):
    """Every position-changing call stops while the oracle sample is stale."""
    assets = 1_430 * ONE
    debt = open_position(protocol.engine, assets, RATE_LOW, protocol.user)
    prev, nxt = hints_for(protocol.engine, RATE_MID, skip=protocol.user)
    boa.env.time_travel(seconds=3_601)
    rejected = (
        lambda: protocol.engine.open_position(assets, debt, RATE_LOW, ZERO_ADDRESS, ZERO_ADDRESS, sender=protocol.reserve_provider),
        lambda: protocol.engine.add_collateral(ONE, sender=protocol.user),
        lambda: protocol.engine.withdraw_collateral(ONE, sender=protocol.user),
        lambda: protocol.engine.borrow(ONE, sender=protocol.user),
        lambda: protocol.engine.repay(ONE, sender=protocol.user),
        lambda: protocol.engine.close_position(sender=protocol.user),
        lambda: protocol.engine.set_rate(RATE_MID, prev, nxt, sender=protocol.user),
        lambda: protocol.engine.redeem(ONE, 1, sender=protocol.user),
        lambda: protocol.engine.liquidate(protocol.user, sender=protocol.merchant),
    )
    for call in rejected:
        with boa.reverts("Engine: stale oracle"):
            call()


def test_max_collateral_blocks_another_deposit():
    """Supplied crvUSD cannot pass MAX_COLLATERAL_ASSETS."""
    account = boa.env.generate_address("account")
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = deploy_engine(token, vault, asset, oracle, max_collateral=100 * ONE)
    token.bind_vault_engine(engine.address)
    asset.mint(account, 200 * ONE)
    asset.approve(engine.address, MAX_UINT256, sender=account)

    with boa.reverts("Engine: max collateral"):
        open_position(engine, 101 * ONE, RATE_LOW, account)


def test_bad_hint_reverts_and_lower_rate_is_redeemed_first(protocol):
    """Insertion hints must match the list, and redemption starts at the cheapest rate."""
    alice_debt = open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.user)
    with boa.reverts("List: bad hint"):
        protocol.engine.open_position(
            1_430 * ONE,
            1_000 * ONE,
            RATE_MID,
            ZERO_ADDRESS,
            ZERO_ADDRESS,
            sender=protocol.reserve_provider,
        )
    dan_debt = open_position(protocol.engine, 1_430 * ONE, RATE_MID, protocol.reserve_provider)
    protocol.bobc.transfer(protocol.merchant, 10 * ONE, sender=protocol.user)

    assets_out = protocol.engine.redeem(10 * ONE, 4, sender=protocol.merchant)

    assert assets_out == 10 * ONE
    assert protocol.engine.position(protocol.user)[1] == alice_debt - 10 * ONE
    assert protocol.engine.position(protocol.reserve_provider)[1] == dan_debt
    assert_books(protocol.engine, protocol.bobc)


def test_redemption_returns_the_borrower_excess(protocol):
    """Burning the whole principal pays oracle crvUSD and leaves the cushion with the borrower."""
    assets = 1_430 * ONE
    debt = open_position(protocol.engine, assets, RATE_LOW, protocol.user)
    protocol.bobc.transfer(protocol.merchant, debt, sender=protocol.user)
    borrower_before = protocol.asset.balanceOf(protocol.user)

    assets_out = protocol.engine.redeem(debt, 4, sender=protocol.merchant)

    assert assets_out == debt
    assert protocol.asset.balanceOf(protocol.merchant) == debt
    assert protocol.asset.balanceOf(protocol.user) == borrower_before + assets - debt
    assert protocol.engine.head() == ZERO_ADDRESS
    assert_books(protocol.engine, protocol.bobc)


def test_partial_redemption_leaves_the_debt_floor():
    """A redemption that would pass the floor stops on the floor instead."""
    account = boa.env.generate_address("account")
    holder = boa.env.generate_address("holder")
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = deploy_engine(token, vault, asset, oracle, min_debt=100 * ONE)
    token.bind_vault_engine(engine.address)
    asset.mint(account, 2_000 * ONE)
    asset.approve(engine.address, MAX_UINT256, sender=account)
    debt = open_position(engine, 1_430 * ONE, RATE_LOW, account)
    token.transfer(holder, debt, sender=account)

    assets_out = engine.redeem(950 * ONE, 4, sender=holder)

    assert assets_out == 900 * ONE
    assert engine.position(account)[1] == 100 * ONE
    assert_books(engine, token)
