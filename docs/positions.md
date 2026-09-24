# Positions

One address, one position. The engine keeps that position's LlamaLend shares. The shares are the claim on crvUSD. As the lender vault earns interest, `convertToAssets` reports more crvUSD for the same shares. The borrower does not hold the vault token directly.

The oracle rate is BOB per USD, scaled by 1e18. Collateral value in BOB is:

```text
crvUSD in the position * oracle / 1e18
```

The collateral ratio is that value divided by the BOBC debt. A ratio of 1.43e18 means 143%.

## Opening

The deploy default refuses a new borrow that would leave the ratio under 143%. At an oracle of 13 BOB per USD, that cap is the same idea as minting at 9.1 BOB per USD:

```text
13 / 9.1 = 1.429
```

Alice locks **1,098.90 crvUSD** and mints **10,000 BOBC**.

```text
collateral value = 1,098.90 * 13 = 14,285.70 BOB
ratio             = 14,285.70 / 10,000 = 142.9%
```

She can spend the 10,000 BOBC. The 1,098.90 crvUSD stays in LlamaLend under the engine, attributed to her. To take the crvUSD back she must burn the BOBC she owes. Any 10,000 BOBC will do, including tokens she buys after spending the ones she minted.

`borrow` can mint more later, and `withdraw_collateral` can take crvUSD out, but only while the ratio stays at or above 143%. `add_collateral` can always add crvUSD.

## When the oracle moves

The debt stays 10,000 BOBC. The crvUSD balance stays 1,098.90 until someone withdraws, redeems, or liquidates. Only the ratio changes, because the same dollars are worth fewer or more BOB.

**Oracle moves from 13 to 12.** Value is `1,098.90 * 12 = 13,186.80` BOB. The ratio is 131.9%. That is under the 143% borrow line and over the 120% liquidation line. Alice cannot withdraw or borrow more. Nobody can liquidate her. Her loan is still open, and a holder can still redeem it if she is the cheapest rate.

**Oracle moves from 13 to 10.** Value is `1,098.90 * 10 = 10,989` BOB. The ratio is 109.9%, under 120%. The position can be liquidated. That path is in [Liquidation](liquidation.md).

A stale, future, or zero oracle reverts every call that opens, changes, redeems, or liquidates a position. There is no band that freezes the engine once the rate leaves 1 BOB per USD. The rate is allowed to move. The position takes the move.

## Two different yields

LlamaLend yield and borrow interest are not the same flow.

**LlamaLend yield is hers.** It shows up as more crvUSD inside her shares. She can withdraw the extra down to the 143% line. On a maximum borrow she is already on that line, so the first yield only rebuilds the cushion. After the ratio is back above 143%, the excess is withdrawable. Leaving it in the position makes liquidation less likely.

**Borrow interest is the cost of the BOBC.** She picks an annual rate when she opens, between the deploy bounds (default 0.5% to 25%). On every touch, after `dt` seconds:

```text
interest = debt * annual_rate * dt / 365 days / 1e18
```

That interest is added to `debt` and to `fees`. The same amount of BOBC is minted to the engine (`surplus`). It is not a spendable balance for Alice, and this version has no function that withdraws it.

`repay` and `redeem` burn principal only. Principal is `debt - fees`. The caller must hold those tokens. `close_position` burns the principal from the borrower, burns `fees` from the engine, and returns her shares. After a clean close the interest tokens are gone and she has her crvUSD back.

A year with the oracle still at 13, and LlamaLend paying 8%, makes the split concrete. Collateral grows to `1,098.90 * 1.08 = 1,186.81` crvUSD.

- Alice at 0.5% owes 10,050 BOBC. About **82.4 crvUSD** sits above the 143% line, and she can withdraw it. The engine holds the 50 BOBC of interest.
- Dan at 8% owes 10,800 BOBC. The 8% borrow uses up the 8% lending yield. He has nothing to withdraw.

The high rate did not send Dan a bill in a second token. It grew his debt until the cushion was gone. Redemption, below, is the other reason he might still choose that rate.

Next: [Redemption](redemption.md). In the engine, start with `open_position`, then `_accrue`, `withdraw_collateral`, and `close_position`.
