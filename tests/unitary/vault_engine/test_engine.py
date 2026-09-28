import boa

from src import bobc
from tests.utils.protocol import (
    LIQ_CR,
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


def test_open_rejects_debt_one_wei_above_the_minimum_ratio(protocol):
    assets = 1_430 * ONE
    debt = 1_000 * ONE + 1
    prev, nxt = hints_for(protocol.engine, RATE_LOW)

    with boa.reverts("Engine: collateral ratio"):
        protocol.engine.open_position(
            assets, debt, RATE_LOW, prev, nxt, sender=protocol.user
        )

    assert not protocol.engine.position(protocol.user)[5]
    assert protocol.engine.total_debt() == 0
    assert protocol.bobc.totalSupply() == 0


def test_add_collateral_rejects_a_zero_share_vault_deposit():
    borrower = boa.env.generate_address("zero-share borrower")
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = deploy_engine(token, vault, asset, oracle, max_collateral=10**25)
    token.bind_vault_engine(engine.address)
    asset.mint(borrower, 2_000 * ONE)
    asset.approve(engine.address, MAX_UINT256, sender=borrower)
    open_position(engine, 1_430 * ONE, RATE_LOW, borrower)
    asset.mint(vault.address, 10**24)
    position_before = engine.position(borrower)
    user_balance_before = asset.balanceOf(borrower)
    vault_balance_before = asset.balanceOf(vault.address)

    with boa.reverts("Engine: zero shares"):
        engine.add_collateral(1, sender=borrower)

    assert engine.position(borrower) == position_before
    assert asset.balanceOf(borrower) == user_balance_before
    assert asset.balanceOf(vault.address) == vault_balance_before
    assert_books(engine, token)


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


def test_interest_uses_the_contracts_two_stage_integer_rounding(protocol):
    debt = open_position(protocol.engine, 1_430 * ONE, 10**17, protocol.user)
    elapsed = 123_456
    boa.env.time_travel(seconds=elapsed)
    protocol.oracle.setUpdatedAt(boa.env.timestamp)

    expected_interest = debt * 10**17 // ONE * elapsed // YEAR
    assert protocol.engine.pending_interest(protocol.user) == expected_interest

    protocol.engine.add_collateral(ONE, sender=protocol.user)

    position = protocol.engine.position(protocol.user)
    assert position[1] == debt + expected_interest
    assert position[2] == expected_interest
    assert protocol.engine.surplus() == expected_interest
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


def test_healthy_position_cannot_be_liquidated(protocol):
    assets = 1_430 * ONE
    open_position(protocol.engine, assets, RATE_LOW, protocol.user)
    protocol.oracle.setRate(95 * 10**16)

    with boa.reverts("Engine: healthy"):
        protocol.engine.liquidate(protocol.user, sender=protocol.merchant)

    assert protocol.engine.position(protocol.user)[5]
    assert protocol.engine.bad_debt() == 0
    assert_books(protocol.engine, protocol.bobc)


def test_undercollateralized_position_can_be_liquidated(protocol):
    """A stronger BOB lowers the ratio under LIQ_CR and allows liquidation."""
    assets = 1_430 * ONE
    open_position(protocol.engine, assets, RATE_LOW, protocol.user)
    protocol.oracle.setRate(80 * 10**16)
    protocol.engine.add_collateral(ONE, sender=protocol.user)
    debt = protocol.engine.position(protocol.user)[1]
    protocol.bobc.transfer(protocol.merchant, debt, sender=protocol.user)
    before = protocol.asset.balanceOf(protocol.merchant)

    protocol.engine.liquidate(protocol.user, sender=protocol.merchant)

    assert not protocol.engine.position(protocol.user)[5]
    assert protocol.engine.insurance_assets() > 0
    assert protocol.asset.balanceOf(protocol.merchant) > before
    assert_books(protocol.engine, protocol.bobc)


def test_liquidation_rejects_position_at_exact_threshold(protocol):
    protocol.oracle.setRate(12 * ONE // 10)
    protocol.engine.open_position(
        6 * ONE,
        5 * ONE,
        RATE_LOW,
        ZERO_ADDRESS,
        ZERO_ADDRESS,
        sender=protocol.user,
    )
    protocol.oracle.setRate(ONE)
    assert protocol.engine.collateral_ratio(protocol.user) == LIQ_CR

    with boa.reverts("Engine: healthy"):
        protocol.engine.liquidate(protocol.user, sender=protocol.merchant)

    assert protocol.engine.position(protocol.user)[5]
    assert_books(protocol.engine, protocol.bobc)


def test_liquidation_rejects_caller_without_required_bobc(protocol):
    debt = open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.user)
    protocol.oracle.setRate(8 * 10**17)
    before = protocol.engine.position(protocol.user)

    with boa.reverts():
        protocol.engine.liquidate(protocol.user, sender=protocol.merchant)

    assert protocol.engine.position(protocol.user) == before
    assert protocol.engine.total_debt() == debt
    assert protocol.engine.bad_debt() == 0
    assert protocol.asset.balanceOf(protocol.merchant) == 0
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


def test_zero_and_future_oracle_samples_are_rejected(protocol):
    open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.user)
    before = protocol.engine.position(protocol.user)

    protocol.oracle.setRate(0)
    with boa.reverts("Engine: zero rate"):
        protocol.engine.add_collateral(ONE, sender=protocol.user)
    assert protocol.engine.position(protocol.user) == before

    protocol.oracle.setRate(ONE)
    protocol.oracle.setUpdatedAt(boa.env.timestamp + 1)
    with boa.reverts("Engine: future oracle"):
        protocol.engine.add_collateral(ONE, sender=protocol.user)
    assert protocol.engine.position(protocol.user) == before
    assert_books(protocol.engine, protocol.bobc)


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


def test_bad_insertion_hint_reverts_without_mutating_the_list(protocol):
    open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.user)
    before_head = protocol.engine.head()
    before_next = protocol.engine.next(protocol.user)
    before_debt = protocol.engine.total_debt()

    with boa.reverts("List: bad hint"):
        protocol.engine.open_position(
            1_430 * ONE,
            1_000 * ONE,
            RATE_MID,
            ZERO_ADDRESS,
            ZERO_ADDRESS,
            sender=protocol.reserve_provider,
        )

    assert protocol.engine.head() == before_head
    assert protocol.engine.next(protocol.user) == before_next
    assert protocol.engine.total_debt() == before_debt
    assert not protocol.engine.position(protocol.reserve_provider)[5]
    assert_books(protocol.engine, protocol.bobc)


def test_lower_rate_is_redeemed_first(protocol):
    alice_debt = open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.user)
    dan_debt = open_position(protocol.engine, 1_430 * ONE, RATE_MID, protocol.reserve_provider)
    protocol.bobc.transfer(protocol.merchant, 10 * ONE, sender=protocol.user)

    assets_out = protocol.engine.redeem(10 * ONE, 4, sender=protocol.merchant)

    assert assets_out == 10 * ONE
    assert protocol.engine.position(protocol.user)[1] == alice_debt - 10 * ONE
    assert protocol.engine.position(protocol.reserve_provider)[1] == dan_debt
    assert_books(protocol.engine, protocol.bobc)


def test_set_rate_rejects_hints_that_were_stale_before_unlink(protocol):
    open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.user)
    open_position(protocol.engine, 1_430 * ONE, RATE_MID, protocol.reserve_provider)
    before = protocol.engine.position(protocol.reserve_provider)

    with boa.reverts("List: bad hint"):
        protocol.engine.set_rate(
            RATE_LOW,
            ZERO_ADDRESS,
            ZERO_ADDRESS,
            sender=protocol.reserve_provider,
        )

    assert protocol.engine.position(protocol.reserve_provider) == before
    assert protocol.engine.head() == protocol.user
    assert protocol.engine.next(protocol.user) == protocol.reserve_provider
    assert_books(protocol.engine, protocol.bobc)


def test_equal_rates_keep_the_order_selected_by_hints(protocol):
    open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.user)
    open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.reserve_provider)

    assert protocol.engine.head() == protocol.user
    assert protocol.engine.next(protocol.user) == protocol.reserve_provider
    assert protocol.engine.next(protocol.reserve_provider) == ZERO_ADDRESS


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


def test_redemption_rounds_assets_down_at_the_oracle_rate(protocol):
    debt = open_position(protocol.engine, 1_430 * ONE, RATE_LOW, protocol.user)
    protocol.oracle.setRate(3 * ONE)
    protocol.bobc.transfer(protocol.merchant, ONE, sender=protocol.user)

    assets_out = protocol.engine.redeem(ONE, 1, sender=protocol.merchant)

    assert assets_out == ONE // 3
    assert protocol.engine.position(protocol.user)[1] == debt - ONE
    assert protocol.bobc.balanceOf(protocol.merchant) == 0
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


def test_repay_cannot_leave_a_fee_only_position_linked():
    """The final principal must be cleared through close_position."""
    borrower = boa.env.generate_address("fee-only repay borrower")
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = deploy_engine(token, vault, asset, oracle, min_debt=1_000 * ONE)
    token.bind_vault_engine(engine.address)
    collateral = 28_600 * ONE
    principal = 20_000 * ONE
    asset.mint(borrower, collateral)
    asset.approve(engine.address, MAX_UINT256, sender=borrower)
    prev, nxt = hints_for(engine, 25 * 10**16)
    engine.open_position(collateral, principal, 25 * 10**16, prev, nxt, sender=borrower)

    boa.env.time_travel(seconds=73 * 24 * 60 * 60)
    oracle.setUpdatedAt(boa.env.timestamp)
    fees = engine.pending_interest(borrower)
    assert fees == 1_000 * ONE
    position_before = engine.position(borrower)
    debt_before = engine.total_debt()
    surplus_before = engine.surplus()
    borrower_bobc_before = token.balanceOf(borrower)

    with boa.reverts("Engine: close position"):
        engine.repay(principal, sender=borrower)

    assert engine.position(borrower) == position_before
    assert engine.total_debt() == debt_before
    assert engine.surplus() == surplus_before
    assert token.balanceOf(borrower) == borrower_bobc_before
    assert engine.position(borrower)[1] > engine.position(borrower)[2]

    engine.close_position(sender=borrower)

    assert not engine.position(borrower)[5]
    assert engine.head() == ZERO_ADDRESS
    assert token.balanceOf(borrower) == 0
    assert asset.balanceOf(borrower) == collateral
    assert engine.total_debt() == engine.surplus() == 0
    assert_books(engine, token)


def test_final_principal_guard_prevents_zero_cost_liquidation():
    """A liquidator must pay principal for collateral after fees accrue."""
    borrower = boa.env.generate_address("zero-cost liquidation borrower")
    liquidator = boa.env.generate_address("zero-cost liquidator")
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(13 * ONE)
    token = bobc.deploy()
    engine = deploy_engine(token, vault, asset, oracle, min_debt=1_000 * ONE)
    token.bind_vault_engine(engine.address)

    collateral = 1_100 * ONE
    asset.mint(borrower, collateral)
    asset.approve(engine.address, MAX_UINT256, sender=borrower)
    principal = open_position(engine, collateral, 25 * 10**16, borrower, rate=13 * ONE)
    assert principal == 10_000 * ONE

    boa.env.time_travel(seconds=5 * YEAR)
    oracle.setUpdatedAt(boa.env.timestamp)
    assert engine.pending_interest(borrower) == 12_500 * ONE
    position_before = engine.position(borrower)
    total_debt_before = engine.total_debt()
    surplus_before = engine.surplus()
    supply_before = token.totalSupply()

    with boa.reverts("Engine: close position"):
        engine.repay(principal, sender=borrower)

    assert engine.position(borrower) == position_before
    assert engine.total_debt() == total_debt_before
    assert engine.surplus() == surplus_before

    # Before the guard, this fee-only state let liquidation pay its caller zero BOBC.
    # The intact position still has principal, so a caller with no BOBC cannot seize it.
    with boa.reverts():
        engine.liquidate(borrower, sender=liquidator)

    assert engine.position(borrower) == position_before
    assert engine.total_debt() == total_debt_before
    assert engine.surplus() == surplus_before
    assert token.totalSupply() == supply_before
    assert asset.balanceOf(liquidator) == 0
    assert_books(engine, token)


def test_redemption_cleans_32_fee_only_positions_and_returns_collateral():
    """Fee-only nodes from 32 minimum-rate borrowers cannot starve later redemption."""
    asset = MOCK_ERC20.deploy("Curve USD", "crvUSD")
    vault = MOCK_ERC4626.deploy(asset.address)
    oracle = MOCK_PEG_ORACLE.deploy(ONE)
    token = bobc.deploy()
    engine = deploy_engine(token, vault, asset, oracle, min_debt=1_000 * ONE)
    token.bind_vault_engine(engine.address)

    borrowers = [boa.env.generate_address(f"minimum-rate borrower {i}") for i in range(32)]
    holder = boa.env.generate_address("later-rate holder")
    redeemer = boa.env.generate_address("redemption holder")
    collateral = 1_430 * ONE

    for borrower in borrowers:
        asset.mint(borrower, collateral)
        asset.approve(engine.address, MAX_UINT256, sender=borrower)
        assert open_position(engine, collateral, RATE_LOW, borrower) == 1_000 * ONE
    asset.mint(holder, collateral)
    asset.approve(engine.address, MAX_UINT256, sender=holder)
    assert open_position(engine, collateral, RATE_MID, holder) == 1_000 * ONE

    # Deployment uses a 0.5% minimum annual rate and 32 redemption steps.
    boa.env.time_travel(seconds=YEAR)
    oracle.setUpdatedAt(boa.env.timestamp)
    for borrower in borrowers:
        token.transfer(redeemer, 1_000 * ONE, sender=borrower)

    assets_out = engine.redeem(32_000 * ONE, 32, sender=redeemer)

    assert assets_out == 32_000 * ONE
    assert engine.head() == holder
    assert engine.next(holder) == ZERO_ADDRESS
    for borrower in borrowers:
        assert not engine.position(borrower)[5]
        assert asset.balanceOf(borrower) == 430 * ONE
    assert_books(engine, token)

    # The higher-rate position remains redeemable after the full 32-node pass.
    holder_balance_before = asset.balanceOf(holder)
    holder_assets_out = engine.redeem(1_000 * ONE, 32, sender=holder)

    assert holder_assets_out == 1_000 * ONE
    assert asset.balanceOf(holder) == holder_balance_before + collateral
    assert engine.head() == ZERO_ADDRESS
    assert not engine.position(holder)[5]
    assert_books(engine, token)
