"""Deterministic replays for stateful strategy boundary mistakes."""
import boa

from tests.fuzz.strategies import near_limit_debt
from tests.utils.protocol import (
    MAX_UINT256,
    MIN_CR,
    ONE,
    RATE_LOW,
    RATE_MID,
    ZERO_ADDRESS,
    hints_for,
)


def test_open_strategy_accounts_for_share_price_rounding(protocol):
    """Replay the standard campaign's 2-wei vault conversion boundary."""
    prior_share_supply = 5_108_529_358_652_499_020_064
    prior_vault_assets = 12_822_473_100_700_967_910_487
    assets = 3_272 * ONE
    rate = 1_511_565_186_591_523_513

    protocol.asset.approve(
        protocol.vault.address, MAX_UINT256, sender=protocol.reserve_provider
    )
    protocol.vault.deposit(
        prior_share_supply, protocol.reserve_provider,
        sender=protocol.reserve_provider,
    )
    protocol.asset.mint(
        protocol.vault.address, prior_vault_assets - prior_share_supply
    )
    protocol.oracle.setRate(rate)

    naive_debt = assets * rate // MIN_CR - 2
    with boa.reverts("Engine: collateral ratio"):
        protocol.engine.open_position(
            assets, naive_debt, RATE_LOW, ZERO_ADDRESS, ZERO_ADDRESS,
            sender=protocol.user,
        )

    safe_debt = near_limit_debt(
        protocol.vault, protocol.asset, assets, rate, MIN_CR
    )
    assert safe_debt == 3_458_630_273_096_129_324_846
    protocol.engine.open_position(
        assets, safe_debt, RATE_LOW, ZERO_ADDRESS, ZERO_ADDRESS,
        sender=protocol.user,
    )
    assert protocol.engine.position(protocol.user)[1] == safe_debt


def test_bad_hint_replay_accounts_for_vault_share_rounding(protocol):
    """The invalid-hint action must pass collateral checks before testing hints."""
    open_assets = 1_430 * ONE
    open_debt = open_assets * ONE // MIN_CR
    protocol.engine.open_position(
        open_assets, open_debt, RATE_LOW, ZERO_ADDRESS, ZERO_ADDRESS,
        sender=protocol.user,
    )
    second_assets = 2_860 * ONE
    second_debt = second_assets * ONE // MIN_CR
    prev, nxt = hints_for(protocol.engine, RATE_MID)
    protocol.engine.open_position(
        second_assets, second_debt, RATE_MID, prev, nxt,
        sender=protocol.reserve_provider,
    )

    # Reproduce the yield adjusted exchange rate and oracle sample from the
    # standard campaign trace. The new deposit converts back two wei lower.
    protocol.asset.mint(protocol.vault.address, 3_145 * ONE)
    rate = 1_233_704_959_393_977_600
    protocol.oracle.setRate(rate)
    borrower = boa.env.generate_address("invalid hint replay borrower")
    assets = 1_500 * ONE
    protocol.asset.mint(borrower, assets)
    protocol.asset.approve(protocol.engine.address, 2**256 - 1, sender=borrower)
    debt = near_limit_debt(protocol.vault, protocol.asset, assets, rate, MIN_CR)
    unlinked_hint = boa.env.generate_address("invalid hint replay node")

    with boa.reverts("List: bad hint"):
        protocol.engine.open_position(
            assets, debt, RATE_LOW, unlinked_hint, ZERO_ADDRESS, sender=borrower
        )
