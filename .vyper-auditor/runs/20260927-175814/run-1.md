<!--RUN pass=1 agents=12/12-->

Completeness: 7 unique (file, function) in raw, 7 covered in final, 0 rejected with reasons. All twelve specialties completed. Pass 1 combined one confirmed liveness finding and eight unresolved leads. The frozen source predates the workspace changes; the repayment defect was later reproduced, fixed, and regression-tested.

The zero-share lead depends on the configured Curve vault accepting a positive deposit for zero shares. Current Curve Vault source rejects zero shares, but the exact bytecode at the configured Arbitrum address was not verified because the fork RPC was unavailable. The oracle leads describe behavior already present in the documentation; whether to relax that gate remains a protocol policy decision.

<!--F key=src-vault-engine-vy|repay|redemption-step-poisoning conf=75 kind=FINDING agents=10,11-->

[75] **Borrowers can block redemption with fee-only positions**

`src/vault_engine.vy.repay` · Confidence: 75

**Description**
A borrower can repay all principal from 32 positions and leave fee-only nodes at the list head, so every holder's redemption reverts.

**Proof**
`repay` checks `amount <= principal` and `pos.debt - amount >= MIN_DEBT`, then subtracts `amount` without checking that principal remains. With the deployment defaults, 32 positions can each hold 20,000 BOBC debt against 28,600 crvUSD collateral, for 915,200 crvUSD total. At 25% annual interest, 73 days adds 1,000 BOBC fees to each position. A borrower can then repay all 20,000 BOBC principal, leaving `pos.debt == pos.fees == MIN_DEBT` while keeping the position linked. Each `_redeem_from` call returns zero for a position with no principal. `redeem` visits at most 32 nodes and reverts with `Engine: nothing redeemed` before it reaches later positions. The collateral ratio after accrual is about 136%, above the 120% liquidation threshold, so a third party cannot clear these nodes by liquidation. The borrowers can close the positions, but only they can choose to do so.

**Fix**

```diff
     assert amount <= principal, "Engine: exceeds principal"
     assert pos.debt - amount >= MIN_DEBT, "Engine: debt floor"
+    assert amount < principal, "Engine: close position"
```

<!--/F-->

<!--F key=src-vault-engine-vy|add-collateral|zero-share-deposit kind=LEAD agents=1,7,8-->

- **A borrower can lose a collateral addition** — `src/vault_engine.vy.add_collateral` — Code smells: the function adds the vault's returned share count without checking that it is positive. Unverified: whether the configured Arbitrum vault uses code that accepts a positive deposit for zero shares; current Curve Vault source rejects that result, but the deployed bytecode was not checked.

<!--/F-->

<!--F key=src-vault-engine-vy|-pull-deposit|zero-share-deposit kind=LEAD agents=9-->

- **The deposit helper accepts zero vault shares** — `src/vault_engine.vy._pull_deposit` — Code smells: the helper transfers the user's assets, calls `deposit`, and returns the share count without a positive-share check. Unverified: whether the configured vault can return zero shares for an accepted deposit.

<!--/F-->

<!--F key=src-vault-engine-vy|redeem|redemption-head-starvation kind=LEAD agents=5-->

- **Undercollateralized head positions can stop redemption** — `src/vault_engine.vy.redeem` — Code smells: the bounded walk can spend all 32 visits on positions that `_redeem_from` cannot redeem. Unverified: whether keeper activity and liquidation incentives always clear 32 such positions before a holder calls `redeem`.

<!--/F-->

<!--F key=src-vault-engine-vy|-redeem-all|vault-liquidity-lock kind=LEAD agents=5,12-->

- **The vault can reject a full position withdrawal** — `src/vault_engine.vy._redeem_all` — Code smells: the helper requests every assigned share, and `IERC4626` does not expose `maxRedeem`. Unverified: whether the deployed vault has less liquid crvUSD than an assigned position requires at the time of close or liquidation.

<!--/F-->

<!--F key=src-vault-engine-vy|-payout|no-underwater-liquidation-reward kind=LEAD agents=3-->

- **A liquidator may receive no gain on underwater debt** — `src/vault_engine.vy._payout` — Code smells: the underwater branch values burned BOBC at the oracle rate and pays only the collateral and insurance available. Unverified: the BOBC market price and keeper costs when that branch runs.

<!--/F-->

<!--F key=src-vault-engine-vy|close-position|oracle-outage-blocks-risk-reduction kind=LEAD agents=3-->

- **A stale oracle blocks position closure** — `src/vault_engine.vy.close_position` — Code smells: `_checked_rate` runs before principal burn, fee burn, or collateral return. Unverified: whether the protocol intends an oracle outage to stop borrowers from closing positions.

<!--/F-->

<!--F key=src-vault-engine-vy|repay|oracle-outage-blocks-risk-reduction kind=LEAD agents=3-->

- **A stale oracle blocks principal repayment** — `src/vault_engine.vy.repay` — Code smells: `_checked_rate` runs before the borrower burns principal BOBC. Unverified: whether the protocol intends an oracle outage to stop debt reduction.

<!--/F-->

<!--F key=src-vault-engine-vy|add-collateral|oracle-outage-blocks-risk-reduction kind=LEAD agents=3-->

- **A stale oracle blocks collateral addition** — `src/vault_engine.vy.add_collateral` — Code smells: `_checked_rate` runs before the borrower can deposit more crvUSD. Unverified: whether the protocol intends an oracle outage to stop collateral additions.

<!--/F-->
