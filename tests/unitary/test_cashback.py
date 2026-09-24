import boa

from tests.conftest import ONE, RATE_MID, open_position


def _seed_pool(protocol):
    debt = open_position(protocol.engine, 200 * ONE, RATE_MID, protocol.reserve_provider)
    protocol.bobc.transfer(protocol.cashback.address, debt, sender=protocol.reserve_provider)


def _fund_payer(protocol, amount):
    assets = (amount * protocol.engine.MIN_CR() + ONE - 1) // ONE
    debt = open_position(protocol.engine, assets, RATE_MID, protocol.user)
    assert debt >= amount
    protocol.bobc.approve(protocol.cashback.address, amount, sender=protocol.user)


def test_t7_cashback_pay_anyone(protocol):
    """T7: any payer can pay a receiver and receive the configured rebate."""
    _seed_pool(protocol)
    amount = 100 * ONE
    _fund_payer(protocol, amount)

    rebate = protocol.cashback.pay(protocol.merchant, amount, sender=protocol.user)

    assert rebate == ONE
    assert protocol.bobc.balanceOf(protocol.merchant) == amount
    assert protocol.bobc.balanceOf(protocol.user) == rebate


def test_t8_empty_cashback_pool_reverts_entire_payment(protocol):
    """T8: an empty reward pool reverts without moving payer funds."""
    _seed_pool(protocol)
    pool_balance = protocol.bobc.balanceOf(protocol.cashback.address)
    protocol.bobc.transfer(protocol.deployer, pool_balance, sender=protocol.cashback.address)
    amount = 100 * ONE
    _fund_payer(protocol, amount)

    with boa.reverts("Cashback: empty pool"):
        protocol.cashback.pay(protocol.merchant, amount, sender=protocol.user)

    assert protocol.bobc.balanceOf(protocol.user) == amount
    assert protocol.bobc.balanceOf(protocol.merchant) == 0


def test_t9_pay_does_not_increase_total_supply(protocol):
    """T9: pay only moves existing BOBC; it never invokes the mint role."""
    _seed_pool(protocol)
    amount = 250 * ONE
    _fund_payer(protocol, amount)
    supply_before = protocol.bobc.totalSupply()

    protocol.cashback.pay(protocol.merchant, amount, sender=protocol.user)

    assert protocol.bobc.totalSupply() == supply_before
