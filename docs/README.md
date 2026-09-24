# How BOBC works

Read these pages before the Vyper. They describe the contracts that are in the repository now.

BOBC is a collateralized debt position on Arbitrum. A borrower locks crvUSD. The engine supplies that crvUSD to the Curve LlamaLend lender vault and mints BOBC as the borrower's debt. The target is 1 BOBC ≈ 1 BOB. The oracle reports how many BOB one USD buys. crvUSD is treated as one USD.

This is not a shared reserve. One address has one position. If BOB strengthens against the dollar, that borrower's collateral ratio falls. Other borrowers are left alone. Holders of BOBC can still exit by redeeming, and an underwater position can be liquidated.

## Three roles

- **Borrower.** Locks crvUSD, receives BOBC, and can spend it. Keeps the LlamaLend yield above the safety line. Chooses an interest rate. Repays BOBC to unlock the crvUSD.
- **Holder.** Someone who received BOBC, often because a borrower spent it. Burns BOBC to take crvUSD at the oracle from the cheapest open loan.
- **Liquidator.** Closes a position whose collateral ratio is under 120%. Burns that position's debt and receives crvUSD, including a penalty.

## Reading order

1. [Positions](positions.md) — collateral, debt, the oracle, and the two yields.
2. [Redemption](redemption.md) — why a cheap interest rate is closed first.
3. [Liquidation](liquidation.md) — the penalty, insurance, and bad debt.
4. [Contracts](contracts.md) — which file to open, and in what order.

The short version also lives in the repository [README](../README.md).
