<!--RUN pass=2 agents=12/12-->

Completeness: 8 unique (file, function) in raw, 8 covered in final, 0 rejected with reasons.

The frozen source snapshot predates the current workspace fixes. The fee-only repayment finding is fixed in the workspace and has a deterministic regression test at `tests/unitary/vault_engine/test_engine.py::test_repay_cannot_leave_a_fee_only_position_linked`. Zero-share deposits are also rejected in the current workspace; the leads below describe the frozen snapshot and retain unverified external-vault assumptions.

<!--F key=src-vault-engine-vy|repay|redemption-step-poisoning conf=75 kind=FINDING agents=3,4,5,6,7,8,9,10,11,12-->

[75] **Borrowers can block redemption with fee-only positions**

`src/vault_engine.vy.repay` · Confidence: 75

**Description**
A borrower can leave 32 fee-only positions at the list head, so BOBC holders cannot redeem collateral.

**Proof**
The frozen deployment defaults set `MIN_DEBT=1,000 BOBC`, `MIN_CR=143%`, and `MIN_ANNUAL_RATE=0.5%`. A borrower opens a position with 200,000 BOBC debt and 22,100 crvUSD collateral at an oracle rate of 13 BOBC per crvUSD. After one year at 0.5%, accrued fees reach 1,000 BOBC. `repay(200,000e18)` leaves `pos.debt == pos.fees == MIN_DEBT` and does not unlink the node. Thirty-two positions use 707,200 crvUSD, below the 1,000,000 crvUSD cap. Equal-rate hints place them ahead of later positions. `_redeem_from` returns zero for fee-only debt, so `redeem` visits 32 nodes and reverts with `Engine: nothing redeemed`. The current workspace rejects repayment at or above principal and tests this case.

**Fix**

```diff
@@
     assert amount <= principal, "Engine: repay too much"
     assert pos.debt - amount >= MIN_DEBT, "Engine: below min debt"
+    assert amount < principal, "Engine: close position"
```

<!--/F-->

<!--F key=src-vault-engine-vy|borrow|fresh-oracle-rate-manipulation kind=LEAD agents=3,12-->

- **A borrower may mint excess BOBC** — `src/vault_engine.vy.borrow` — Code smells: `_checked_rate` checks positivity and freshness but no deviation bound, and `borrow` uses the rate to approve debt — Unverified: the configured oracle implementation and update controls are outside the frozen source, so resistance to a fresh overstated sample is unknown.

<!--/F-->

<!--F key=src-vault-engine-vy|repay|oracle-outage-blocks-risk-reduction kind=LEAD agents=4,5,6,7,9,11,12-->

- **A borrower cannot repay during a prolonged oracle outage** — `src/vault_engine.vy.repay` — Code smells: `repay` calls `_checked_rate()` before accruing debt or burning BOBC, although repayment does not use collateral value — Unverified: whether the oracle can stop publishing for longer than the configured 3,600-second freshness window is unknown.

<!--/F-->

<!--F key=src-vault-engine-vy|add-collateral|oracle-outage-blocks-risk-reduction kind=LEAD agents=4,5,6,7,9,11,12-->

- **A borrower cannot add collateral during a prolonged oracle outage** — `src/vault_engine.vy.add_collateral` — Code smells: `add_collateral` calls `_checked_rate()` before the deposit although the operation adds collateral and does not use the returned rate — Unverified: whether the oracle can stop publishing for longer than the configured 3,600-second freshness window is unknown.

<!--/F-->

<!--F key=src-vault-engine-vy|add-collateral|zero-share-deposit kind=LEAD agents=1,3,4,5,6,7,8,9,10,11,12-->

- **A borrower may lose a crvUSD deposit** — `src/vault_engine.vy.add_collateral` — Code smells: `add_collateral` accepts the shares returned by `_pull_deposit` without requiring a positive amount — Unverified: the configured Curve LlamaLend vault's exact deployed bytecode is not verified here, and it must accept a positive deposit while returning zero shares.

<!--/F-->

<!--F key=src-vault-engine-vy|-pull-deposit|zero-share-deposit kind=LEAD agents=1,3,4,5,6,7,8,9,10,11,12-->

- **A vault deposit may transfer crvUSD without recording shares** — `src/vault_engine.vy._pull_deposit` — Code smells: the helper adds returned shares to `total_shares` and returns even when the vault returns zero — Unverified: the configured Curve LlamaLend vault's exact deployed bytecode is not verified here, and it must accept a positive deposit while returning zero shares.

<!--/F-->

<!--F key=src-vault-engine-vy|redeem|redemption-head-starvation kind=LEAD agents=3,4,5,6,7,8,9,10,11,12-->

- **A BOBC holder may not reach later positions** — `src/vault_engine.vy.redeem` — Code smells: the loop visits at most 32 nodes, `_redeem_from` returns zero for positions below `LIQ_CR`, and the call reverts when it pays nothing — Unverified: the blocking state requires 32 consecutive unhealthy positions at the head and no liquidation or closure that clears them.

<!--/F-->

<!--F key=src-vault-engine-vy|-redeem-all|vault-liquidity-lock kind=LEAD agents=3,4,5,6,7,8,9,11,12-->

- **A borrower may be unable to close during vault illiquidity** — `src/vault_engine.vy._redeem_all` — Code smells: the helper requests redemption of all assigned shares without checking available liquidity or handling a partial redemption — Unverified: the configured vault's exact deployed behavior and available liquidity are not verified here.

<!--/F-->

<!--F key=src-vault-engine-vy|-payout|no-underwater-liquidation-reward kind=LEAD agents=1,3,4,5,6,7,8,9,11,12-->

- **Liquidators may receive no premium for underwater collateral** — `src/vault_engine.vy._payout` — Code smells: the underwater branch pays oracle-value assets and adds no explicit liquidation bonus — Unverified: market discounts, keeper policies, insurance value, and liquidator gas costs are unknown.

<!--/F-->

<!--F key=src-vault-engine-vy|close-position|oracle-outage-blocks-risk-reduction kind=LEAD agents=4,5,6,7,9,11,12-->

- **A borrower cannot close during a prolonged oracle outage** — `src/vault_engine.vy.close_position` — Code smells: `close_position` calls `_checked_rate()` before accruing debt or redeeming collateral, although closure does not use the returned rate — Unverified: whether the oracle can stop publishing for longer than the configured 3,600-second freshness window is unknown.

<!--/F-->
