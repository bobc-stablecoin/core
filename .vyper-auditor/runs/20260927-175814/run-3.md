<!--RUN pass=3 agents=12/12-->

Completeness: 13 unique (file, function) in raw, 13 covered in final, 0 rejected with reasons.

This pass reviewed the frozen source snapshot captured before the workspace fixes. The fee-only repayment defect is fixed in the workspace; the deterministic tests cover both redemption starvation and the zero-cost liquidation enabled by the same state transition. The zero-share deposit lead is also fixed in the workspace. Other leads depend on external oracle, token, or ERC-4626 vault behavior that was not verified against the configured Arbitrum deployment because `ARBITRUM_RPC` is unavailable.

<!--F key=src-vault-engine-vy|repay|redemption-step-poisoning conf=75 kind=FINDING agents=1,2,3,4,5,6,7,8,9,10,11,12-->

[75] **Repaying final principal can enable free liquidation and block redemption**

`src/vault_engine.vy.repay` · Confidence: 75

**Description**
An attacker can liquidate a fee-only position without BOBC, while 32 such positions also block holders from redeeming later debt.

**Proof**
The frozen `repay` path accepts `amount == principal` if `pos.debt - amount >= MIN_DEBT`, then leaves the fee-only position linked. With deployment defaults, a borrower opens 10,000 BOBC debt against 1,100 crvUSD at an oracle rate of 13 BOB/USD and a 25% annual rate. After five years, interest is 12,500 BOBC. Repaying the 10,000 BOBC principal leaves `debt == fees == 12,500`; the position ratio is about 114.4%, below `LIQ_CR = 120%`. `_payout` sets `bobc_from_liquidator = debt - fees = 0`, yet the solvent branch pays the liquidator about 1,000 crvUSD and burns the engine-held fees. The borrower could instead use `close_position` and recover the collateral. The same fee-only state blocks redemption: 32 positions opened at 200,000 BOBC debt and 22,100 crvUSD collateral at 13 BOB/USD, accruing 1,000 BOBC fees at the 0.5% minimum rate over one year, fit under the 1,000,000 crvUSD cap. After repaying principal, each can withdraw excess collateral while keeping the fee debt above `MIN_DEBT`; the 32 zero-principal nodes consume the redemption limit and `redeem` reverts with `Engine: nothing redeemed`. The workspace rejects repayment at or above principal and has regression tests for both effects.

**Fix**

```diff
@@
     assert amount <= principal, "Engine: repay too much"
     assert pos.debt - amount >= MIN_DEBT, "Engine: below min debt"
+    assert amount < principal, "Engine: close position"
```

<!--/F-->

<!--F key=src-vault-engine-vy|borrow|fresh-oracle-rate-manipulation kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A borrower may mint excess BOBC** — `src/vault_engine.vy.borrow` — Code smells: `_checked_rate` checks positivity and freshness but has no deviation bound, and `borrow` uses the rate to approve debt — Unverified: the configured oracle implementation and update controls are outside the frozen source, so resistance to a fresh overstated sample is unknown.

<!--/F-->

<!--F key=src-vault-engine-vy|repay|oracle-outage-blocks-risk-reduction kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A borrower cannot repay during an oracle outage** — `src/vault_engine.vy.repay` — Code smells: `repay` calls `_checked_rate()` before accruing debt or burning BOBC although repayment does not use collateral value — Unverified: whether the oracle can stop publishing beyond the configured 3,600-second freshness window is unknown.

<!--/F-->

<!--F key=src-vault-engine-vy|add-collateral|oracle-outage-blocks-risk-reduction kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A borrower cannot add collateral during an oracle outage** — `src/vault_engine.vy.add_collateral` — Code smells: `add_collateral` calls `_checked_rate()` before depositing although it does not use the returned rate — Unverified: whether oracle downtime should block collateral additions is a protocol policy question.

<!--/F-->

<!--F key=src-vault-engine-vy|add-collateral|zero-share-deposit kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A borrower may lose a crvUSD deposit** — `src/vault_engine.vy.add_collateral` — Code smells: the frozen function adds the vault's returned shares without requiring a positive amount — Unverified: the exact deployed vault bytecode was not checked; the current workspace rejects zero-share deposits.

<!--/F-->

<!--F key=src-vault-engine-vy|-pull-deposit|zero-share-deposit kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A vault deposit may transfer crvUSD without recording shares** — `src/vault_engine.vy._pull_deposit` — Code smells: the frozen helper records and returns zero shares after a positive deposit — Unverified: whether the configured vault can accept a positive deposit while returning zero shares is unknown; the current workspace rejects this result.

<!--/F-->

<!--F key=src-vault-engine-vy|redeem|redemption-head-starvation kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A BOBC holder may not reach later positions** — `src/vault_engine.vy.redeem` — Code smells: the loop visits at most 32 nodes, `_redeem_from` skips positions below `LIQ_CR` or with no principal, and the call reverts when it pays nothing — Unverified: the blocking state requires 32 consecutive positions that remain non-paying at the list head.

<!--/F-->

<!--F key=src-vault-engine-vy|-redeem-all|vault-liquidity-lock kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A borrower may be unable to close during vault illiquidity** — `src/vault_engine.vy._redeem_all` — Code smells: the helper requests redemption of all assigned shares and has no partial-redemption path — Unverified: the configured vault's withdrawal limits, queue behavior, and available liquidity require verification at a pinned fork block.

<!--/F-->

<!--F key=src-vault-engine-vy|-payout|no-underwater-liquidation-reward kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A liquidator may receive no premium for underwater collateral** — `src/vault_engine.vy._payout` — Code smells: the underwater branch pays only the available asset pot and insurance — Unverified: BOBC's market price, keeper policies, and execution costs determine whether external incentives cover liquidation.

<!--/F-->

<!--F key=src-vault-engine-vy|close-position|oracle-outage-blocks-risk-reduction kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A borrower cannot close during an oracle outage** — `src/vault_engine.vy.close_position` — Code smells: `close_position` calls `_checked_rate()` before clearing debt or redeeming collateral although closure does not use the returned rate — Unverified: whether oracle downtime should block closure is a protocol policy question.

<!--/F-->

<!--F key=src-vault-engine-vy|-init-|unbounded-vault-allowance kind=LEAD agents=4,12-->

- **A compromised vault may take idle engine crvUSD** — `src/vault_engine.vy.__init__` — Code smells: the constructor grants the vault `max_value(uint256)` allowance and exposes no revocation route — Unverified: the configured Curve vault's immutability and transfer surface need confirmation.

<!--/F-->

<!--F key=src-vault-engine-vy|liquidate|liquidation-quote-exceeds-vault-proceeds kind=LEAD agents=4,5,6-->

- **A vault fee may make liquidation underfunded or overstate insurance** — `src/vault_engine.vy.liquidate` — Code smells: the engine calculates payouts from `convertToAssets`, ignores actual assets returned by `_redeem_all`, and records the quoted insurance payout — Unverified: the configured Curve vault's withdrawal fees and exact deployed behavior require pinned fork verification; without idle funds the later transfers can revert, while idle funds can leave `insurance_assets` above the actual balance.

<!--/F-->

<!--F key=src-vault-engine-vy|-ratio|crvusd-parity-assumption kind=LEAD agents=6-->

- **A crvUSD depeg may leave BOBC undercollateralized** — `src/vault_engine.vy._ratio` — Code smells: the function values crvUSD at one USD through the BOB-per-USD oracle and reads no crvUSD/USD market price — Unverified: the protocol documents the one-dollar assumption, but its depeg tolerance and external parity support are not established in this source.

<!--/F-->

<!--F key=src-vault-engine-vy|-pull-deposit|fee-on-transfer-insurance-subsidy kind=LEAD agents=4,12-->

- **A fee-on-transfer asset may consume idle insurance** — `src/vault_engine.vy._pull_deposit` — Code smells: the helper requests `assets` from the borrower and deposits the same amount without measuring the engine's received balance — Unverified: the deployed asset is crvUSD, but the constructor accepts any asset matching the vault and exact-transfer behavior is an external assumption.

<!--/F-->

<!--F key=src-vault-engine-vy|redeem|oracle-outage-blocks-redemption kind=LEAD agents=4,12-->

- **A BOBC holder cannot redeem during an oracle outage** — `src/vault_engine.vy.redeem` — Code smells: `redeem` calls `_checked_rate()` before visiting positions or withdrawing collateral — Unverified: whether redemption is intended to pause throughout an oracle outage is a protocol policy question.

<!--/F-->

<!--F key=src-vault-engine-vy|liquidate|oracle-outage-blocks-liquidation kind=LEAD agents=4,12-->

- **A liquidator cannot clear an unsafe position during an oracle outage** — `src/vault_engine.vy.liquidate` — Code smells: `liquidate` checks oracle freshness before accruing, valuing, or clearing the position — Unverified: the duration of outages and any deployment fallback are unknown.

<!--/F-->

<!--F key=src-vault-engine-vy|liquidate|fee-on-transfer-liquidation-payout kind=LEAD agents=4,12-->

- **A fee-on-transfer asset may short a liquidator's payout** — `src/vault_engine.vy.liquidate` — Code smells: the function checks the transfer's boolean result but not the liquidator's or borrower's received balance — Unverified: the documented deployment uses crvUSD, but the constructor accepts another matching asset and exact-transfer behavior is unverified.

<!--/F-->

<!--F key=src-vault-engine-vy|set-rate|oracle-outage-blocks-risk-reduction kind=LEAD agents=5-->

- **A borrower cannot lower future interest during an oracle outage** — `src/vault_engine.vy.set_rate` — Code smells: the function calls `_checked_rate()` before changing the annual rate but does not use the returned value — Unverified: whether oracle downtime should block rate reductions is a protocol policy question.

<!--/F-->

<!--F key=src-vault-engine-vy|-redeem-from|redemption-withdraw-fee-health kind=LEAD agents=5-->

- **A vault withdrawal fee may push a redeemed position below `LIQ_CR`** — `src/vault_engine.vy._redeem_from` — Code smells: the function checks the ratio before `withdraw`, then reduces shares and debt without checking the ratio again — Unverified: the configured vault's withdrawal fee and share burn behavior require pinned fork verification.

<!--/F-->
