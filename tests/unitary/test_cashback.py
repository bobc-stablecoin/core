import boa
import pytest

from src import cashback as cashback_module
from tests.conftest import ONE, RATE_MID, ZERO_ADDRESS, open_position


def _seed_pool(protocol):
    debt = open_position(protocol.engine, 200 * ONE, RATE_MID, protocol.reserve_provider)
    protocol.bobc.transfer(protocol.cashback.address, debt, sender=protocol.reserve_provider)


def _fund_payer(protocol, amount):
    assets = (amount * protocol.engine.MIN_CR() + ONE - 1) // ONE
    debt = open_position(protocol.engine, assets, RATE_MID, protocol.user)
    assert debt >= amount
    protocol.bobc.approve(protocol.cashback.address, amount, sender=protocol.user)


def _approve(protocol, merchant=None):
    protocol.cashback.add_merchant(merchant or protocol.merchant, sender=protocol.deployer)


def test_pay_requires_approved_merchant_without_moving_bobc(protocol):
    _seed_pool(protocol)
    amount = 100 * ONE
    _fund_payer(protocol, amount)
    balances = (
        protocol.bobc.balanceOf(protocol.user),
        protocol.bobc.balanceOf(protocol.merchant),
        protocol.bobc.balanceOf(protocol.cashback.address),
    )

    with boa.reverts("Cashback: unapproved merchant"):
        protocol.cashback.pay(protocol.merchant, amount, sender=protocol.user)

    assert balances == (
        protocol.bobc.balanceOf(protocol.user),
        protocol.bobc.balanceOf(protocol.merchant),
        protocol.bobc.balanceOf(protocol.cashback.address),
    )


def test_pay_rejects_approved_self_recipient_without_moving_bobc(protocol):
    _seed_pool(protocol)
    amount = 100 * ONE
    _fund_payer(protocol, amount)
    _approve(protocol, protocol.user)
    balances = (
        protocol.bobc.balanceOf(protocol.user),
        protocol.bobc.balanceOf(protocol.cashback.address),
    )

    with boa.reverts("Cashback: self payment"):
        protocol.cashback.pay(protocol.user, amount, sender=protocol.user)

    assert balances == (
        protocol.bobc.balanceOf(protocol.user),
        protocol.bobc.balanceOf(protocol.cashback.address),
    )


@pytest.mark.parametrize(("rate", "expected_rebate"), [(0, 0), (100, ONE), (200, 2 * ONE)])
def test_cashback_rate_boundaries_and_rebate_accounting(protocol, rate, expected_rebate):
    _seed_pool(protocol)
    amount = 100 * ONE
    _fund_payer(protocol, amount)
    _approve(protocol)
    protocol.cashback.set_cashback_bps(rate, sender=protocol.deployer)
    supply_before = protocol.bobc.totalSupply()
    pool_before = protocol.bobc.balanceOf(protocol.cashback.address)

    rebate = protocol.cashback.pay(protocol.merchant, amount, sender=protocol.user)
    assert rebate == expected_rebate
    assert protocol.bobc.balanceOf(protocol.merchant) == amount
    assert protocol.bobc.balanceOf(protocol.user) == expected_rebate
    assert protocol.bobc.balanceOf(protocol.cashback.address) == pool_before - expected_rebate
    assert protocol.bobc.totalSupply() == supply_before


def test_cashback_rate_rejects_201_bps_and_constructor_limit(protocol):
    with boa.reverts("Cashback: invalid BPS"):
        protocol.cashback.set_cashback_bps(201, sender=protocol.deployer)
    with boa.reverts("Cashback: invalid BPS"):
        cashback_module.deploy(protocol.bobc.address, 201)
    assert protocol.cashback.CASHBACK_BPS() == 100


def test_cashback_owner_only_management_and_two_step_handoff(protocol):
    merchant = boa.env.generate_address("approved merchant")
    calls = [
        lambda: protocol.cashback.set_cashback_bps(150, sender=protocol.user),
        lambda: protocol.cashback.add_merchant(merchant, sender=protocol.user),
        lambda: protocol.cashback.remove_merchant(merchant, sender=protocol.user),
        lambda: protocol.cashback.clear_merchants(sender=protocol.user),
        lambda: protocol.cashback.set_merchants([merchant], sender=protocol.user),
    ]
    for call in calls:
        with boa.reverts("ownable: caller is not the owner"):
            call()

    protocol.cashback.transfer_ownership(protocol.user, sender=protocol.deployer)
    assert protocol.cashback.owner() == protocol.deployer
    assert protocol.cashback.pending_owner() == protocol.user
    with boa.reverts("ownable: caller is not the owner"):
        protocol.cashback.set_cashback_bps(150, sender=protocol.user)
    protocol.cashback.accept_ownership(sender=protocol.user)
    assert protocol.cashback.owner() == protocol.user
    assert protocol.cashback.pending_owner() == ZERO_ADDRESS
    protocol.cashback.set_cashback_bps(150, sender=protocol.user)
    with boa.reverts("ownable: caller is not the owner"):
        protocol.cashback.set_cashback_bps(100, sender=protocol.deployer)


def test_merchant_add_remove_clear_and_set_keep_membership_synchronized(protocol):
    alice = boa.env.generate_address("merchant alice")
    bob = boa.env.generate_address("merchant bob")
    carol = boa.env.generate_address("merchant carol")

    with boa.reverts("Cashback: zero merchant"):
        protocol.cashback.add_merchant(ZERO_ADDRESS, sender=protocol.deployer)
    protocol.cashback.add_merchant(alice, sender=protocol.deployer)
    with boa.reverts("Cashback: duplicate merchant"):
        protocol.cashback.add_merchant(alice, sender=protocol.deployer)
    assert protocol.cashback.is_merchant(alice)

    with boa.reverts("Cashback: merchant not found"):
        protocol.cashback.remove_merchant(bob, sender=protocol.deployer)
    protocol.cashback.remove_merchant(alice, sender=protocol.deployer)
    assert not protocol.cashback.is_merchant(alice)

    protocol.cashback.set_merchants([alice, bob], sender=protocol.deployer)
    assert tuple(protocol.cashback.get_merchants()) == (alice, bob)
    assert protocol.cashback.is_merchant(alice)
    assert protocol.cashback.is_merchant(bob)
    with boa.reverts("Cashback: duplicate merchant"):
        protocol.cashback.set_merchants([carol, carol], sender=protocol.deployer)
    assert tuple(protocol.cashback.get_merchants()) == (alice, bob)
    with boa.reverts("Cashback: zero merchant"):
        protocol.cashback.set_merchants([carol, ZERO_ADDRESS], sender=protocol.deployer)
    assert tuple(protocol.cashback.get_merchants()) == (alice, bob)

    protocol.cashback.set_merchants([carol], sender=protocol.deployer)
    assert tuple(protocol.cashback.get_merchants()) == (carol,)
    assert not protocol.cashback.is_merchant(alice)
    assert not protocol.cashback.is_merchant(bob)
    assert protocol.cashback.is_merchant(carol)
    protocol.cashback.clear_merchants(sender=protocol.deployer)
    assert tuple(protocol.cashback.get_merchants()) == ()
    assert not protocol.cashback.is_merchant(carol)


def test_merchant_list_accepts_128_and_rejects_129th(protocol):
    merchants = [boa.env.generate_address(f"merchant {i}") for i in range(128)]
    for merchant in merchants:
        protocol.cashback.add_merchant(merchant, sender=protocol.deployer)

    assert len(protocol.cashback.get_merchants()) == 128
    assert protocol.cashback.is_merchant(merchants[-1])
    protocol.cashback.clear_merchants(sender=protocol.deployer)
    protocol.cashback.set_merchants(merchants, sender=protocol.deployer)
    assert len(protocol.cashback.get_merchants()) == 128
    with boa.reverts("Cashback: merchant limit"):
        protocol.cashback.add_merchant(boa.env.generate_address("merchant 129"), sender=protocol.deployer)


def test_empty_cashback_pool_reverts_entire_payment(protocol):
    _seed_pool(protocol)
    pool_balance = protocol.bobc.balanceOf(protocol.cashback.address)
    protocol.bobc.transfer(protocol.deployer, pool_balance, sender=protocol.cashback.address)
    amount = 100 * ONE
    _fund_payer(protocol, amount)
    _approve(protocol)
    balances_before = (
        protocol.bobc.balanceOf(protocol.user),
        protocol.bobc.balanceOf(protocol.merchant),
        protocol.bobc.balanceOf(protocol.cashback.address),
    )

    with boa.reverts("Cashback: empty pool"):
        protocol.cashback.pay(protocol.merchant, amount, sender=protocol.user)

    assert balances_before == (
        protocol.bobc.balanceOf(protocol.user),
        protocol.bobc.balanceOf(protocol.merchant),
        protocol.bobc.balanceOf(protocol.cashback.address),
    )


def test_pay_does_not_increase_total_supply(protocol):
    _seed_pool(protocol)
    amount = 250 * ONE
    _fund_payer(protocol, amount)
    _approve(protocol)
    supply_before = protocol.bobc.totalSupply()

    protocol.cashback.pay(protocol.merchant, amount, sender=protocol.user)

    assert protocol.bobc.totalSupply() == supply_before
