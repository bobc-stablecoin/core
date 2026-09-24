# Liquidation

Redemption shrinks a healthy loan and leaves the cushion with the borrower. Liquidation is the other path. It starts only when the collateral ratio is under 120%, and the caller takes a penalty on top of the debt.

The ratio is checked after interest is accrued, using a fresh oracle. A position at exactly 120% is not liquidated. The deploy default also rejects a penalty that does not fit inside that 120% line, so a liquidation that happens right at the boundary still has crvUSD left for the penalty.

## A move from 13 to 10

Alice still has 1,098.90 crvUSD and owes 10,000 BOBC. At 10 BOB per USD the collateral is worth 10,989 BOB. The ratio is 109.9%. Her debt now claims `10,000 / 10 = 1,000` crvUSD, and she has 1,098.90, so the debt is covered.

The default penalty is 5%: 4% to the liquidator, 1% kept by the engine as idle crvUSD (`insurance_assets`). The caller pays the full 10,000 BOBC (there is no unpaid interest in this example). Of her crvUSD:

- **1,040** goes to the caller (the 1,000 of debt plus 4%).
- **10** stays in the engine as insurance.
- **48.90** returns to Alice.

A redemption at this same oracle would have returned her `1,098.90 - 1,000 = 98.90` crvUSD. The missing 50 crvUSD is the penalty. Her loan is removed from the list.

## A gap from 13 to 8

At 8 BOB per USD the same 1,098.90 crvUSD is worth `1,098.90 * 8 = 8,791.20` BOB. She owes 10,000. The position cannot pay the debt.

With no insurance on hand, the caller pays **8,791.20 BOBC** and takes all 1,098.90 crvUSD. Alice receives nothing. The other **1,208.80 BOBC** stays in circulation with no collateral behind it. That amount is `bad_debt`.

If the engine already holds insurance crvUSD from earlier penalties, that balance is added to the pot first, up to the shortfall. The caller then pays BOBC equal to the oracle value of the crvUSD they actually receive. Only the still-uncovered debt is recorded as `bad_debt`.

Unpaid interest on that position is burned from the engine's own BOBC when the loan is cleared. It is not part of what the liquidator has to bring. Burning it does not fill the hole: those tokens were not circulating. The hole is circulating BOBC with no crvUSD left under it.

## What the books have to match

After the positions involved have been touched:

```text
BOBC.totalSupply = total_debt + bad_debt
```

`total_debt` is the sum of stored position debt, and that sum already includes unpaid interest. The interest BOBC sitting on the engine is the `fees` portion of that debt, so it is not added a second time. `bad_debt` is the part of old debt that was cleared off a position without a matching burn from a caller.

LlamaLend can also shrink the shares if that vault takes a loss. The ratio falls the same way it falls when BOB strengthens, and the same liquidation handles it.

Next: [Contracts](contracts.md). In the engine, read `liquidate` and `_payout`.
