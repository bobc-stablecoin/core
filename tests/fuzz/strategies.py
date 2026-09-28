"""Small exact-integer strategies for protocol inputs and actors."""
from hypothesis import strategies as st

from tests.utils.protocol import ONE, RATE_LOW


def near_limit_debt(vault, asset, assets: int, rate: int, min_cr: int) -> int:
    """Estimate post-deposit collateral using the stateful suite's ERC-4626 mock."""
    supply = vault.totalSupply()
    vault_assets = asset.balanceOf(vault.address)
    shares = assets
    if supply > 0 and vault_assets > 0:
        shares = assets * supply // vault_assets
    if shares == 0:
        return 0
    held = shares * (vault_assets + assets) // (supply + shares)
    return held * rate // min_cr - 2


@st.composite
def collateral_amounts(draw):
    return draw(st.integers(min_value=1_500, max_value=5_000)) * ONE


@st.composite
def rates(draw):
    return draw(st.integers(min_value=RATE_LOW, max_value=25 * 10**16))


@st.composite
def oracle_rates(draw):
    return draw(st.integers(min_value=3 * ONE // 10, max_value=2 * ONE))


@st.composite
def token_amounts(draw, upper: int):
    units = draw(st.integers(min_value=1, max_value=max(1, upper // ONE)))
    return min(units * ONE, upper)
