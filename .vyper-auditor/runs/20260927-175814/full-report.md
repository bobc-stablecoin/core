# 🔐 Security Review — core (Vyper)

---

## Scope

|  |  |
| --- | --- |
| **Mode** | default |
| **Files reviewed** | `src/bobc.vy` · `src/vault_engine.vy` · `src/cashback.vy`<br>`src/sorted_positions.vy` |
| **Compiler context** | Vyper ~=0.4.3 in source; uv.lock and active .venv resolve 0.4.3; Moccasin 0.4.4; pragma nonreentrancy on in bobc, cashback, vault_engine and off in sorted_positions; no explicit EVM pragma or optimizer override found. |
| **Confidence threshold (1-100)** | 75 |
| **Passes** | 3 |
| **Memory** | 0 records before this scan · 19 after · `8eef8b1` |

---

## Findings

[75] **1. Repaying final principal can enable free liquidation and block redemption**

`src/vault_engine.vy.repay` · Confidence: 75 · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] · seen in 3/3 runs · NEW

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

---

Findings List

| # | Confidence | Title |
|---|---|---|
| 1 | [75] | Repaying final principal can enable free liquidation and block redemption |

---

## Leads

_Vulnerability trails with concrete code smells where the full exploit path could not be completed in one analysis pass. These are not false positives — they are high-signal leads for manual review. Not scored._

- **A compromised vault may take idle engine crvUSD** — `src/vault_engine.vy.__init__` · seen in 1/3 runs · NEW · [agents: 4,12] — Code smells: the constructor grants the vault `max_value(uint256)` allowance and exposes no revocation route — Unverified: the configured Curve vault's immutability and transfer surface need confirmation.
- **A liquidator may receive no premium for underwater collateral** — `src/vault_engine.vy._payout` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: the underwater branch pays only the available asset pot and insurance — Unverified: BOBC's market price, keeper policies, and execution costs determine whether external incentives cover liquidation.
- **A fee-on-transfer asset may consume idle insurance** — `src/vault_engine.vy._pull_deposit` · seen in 1/3 runs · NEW · [agents: 4,12] — Code smells: the helper requests `assets` from the borrower and deposits the same amount without measuring the engine's received balance — Unverified: the deployed asset is crvUSD, but the constructor accepts any asset matching the vault and exact-transfer behavior is an external assumption.
- **A vault deposit may transfer crvUSD without recording shares** — `src/vault_engine.vy._pull_deposit` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: the frozen helper records and returns zero shares after a positive deposit — Unverified: whether the configured vault can accept a positive deposit while returning zero shares is unknown; the current workspace rejects this result.
- **A crvUSD depeg may leave BOBC undercollateralized** — `src/vault_engine.vy._ratio` · seen in 1/3 runs · NEW · [agents: 6] — Code smells: the function values crvUSD at one USD through the BOB-per-USD oracle and reads no crvUSD/USD market price — Unverified: the protocol documents the one-dollar assumption, but its depeg tolerance and external parity support are not established in this source.
- **A borrower may be unable to close during vault illiquidity** — `src/vault_engine.vy._redeem_all` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: the helper requests redemption of all assigned shares and has no partial-redemption path — Unverified: the configured vault's withdrawal limits, queue behavior, and available liquidity require verification at a pinned fork block.
- **A vault withdrawal fee may push a redeemed position below `LIQ_CR`** — `src/vault_engine.vy._redeem_from` · seen in 1/3 runs · NEW · [agents: 5] — Code smells: the function checks the ratio before `withdraw`, then reduces shares and debt without checking the ratio again — Unverified: the configured vault's withdrawal fee and share burn behavior require pinned fork verification.
- **A borrower cannot add collateral during an oracle outage** — `src/vault_engine.vy.add_collateral` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: `add_collateral` calls `_checked_rate()` before depositing although it does not use the returned rate — Unverified: whether oracle downtime should block collateral additions is a protocol policy question.
- **A borrower may lose a crvUSD deposit** — `src/vault_engine.vy.add_collateral` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: the frozen function adds the vault's returned shares without requiring a positive amount — Unverified: the exact deployed vault bytecode was not checked; the current workspace rejects zero-share deposits.
- **A borrower may mint excess BOBC** — `src/vault_engine.vy.borrow` · seen in 2/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: `_checked_rate` checks positivity and freshness but has no deviation bound, and `borrow` uses the rate to approve debt — Unverified: the configured oracle implementation and update controls are outside the frozen source, so resistance to a fresh overstated sample is unknown.
- **A borrower cannot close during an oracle outage** — `src/vault_engine.vy.close_position` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: `close_position` calls `_checked_rate()` before clearing debt or redeeming collateral although closure does not use the returned rate — Unverified: whether oracle downtime should block closure is a protocol policy question.
- **A fee-on-transfer asset may short a liquidator's payout** — `src/vault_engine.vy.liquidate` · seen in 1/3 runs · NEW · [agents: 4,12] — Code smells: the function checks the transfer's boolean result but not the liquidator's or borrower's received balance — Unverified: the documented deployment uses crvUSD, but the constructor accepts another matching asset and exact-transfer behavior is unverified.
- **A vault fee may make liquidation underfunded or overstate insurance** — `src/vault_engine.vy.liquidate` · seen in 1/3 runs · NEW · [agents: 4,5,6] — Code smells: the engine calculates payouts from `convertToAssets`, ignores actual assets returned by `_redeem_all`, and records the quoted insurance payout — Unverified: the configured Curve vault's withdrawal fees and exact deployed behavior require pinned fork verification; without idle funds the later transfers can revert, while idle funds can leave `insurance_assets` above the actual balance.
- **A liquidator cannot clear an unsafe position during an oracle outage** — `src/vault_engine.vy.liquidate` · seen in 1/3 runs · NEW · [agents: 4,12] — Code smells: `liquidate` checks oracle freshness before accruing, valuing, or clearing the position — Unverified: the duration of outages and any deployment fallback are unknown.
- **A BOBC holder cannot redeem during an oracle outage** — `src/vault_engine.vy.redeem` · seen in 1/3 runs · NEW · [agents: 4,12] — Code smells: `redeem` calls `_checked_rate()` before visiting positions or withdrawing collateral — Unverified: whether redemption is intended to pause throughout an oracle outage is a protocol policy question.
- **A BOBC holder may not reach later positions** — `src/vault_engine.vy.redeem` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: the loop visits at most 32 nodes, `_redeem_from` skips positions below `LIQ_CR` or with no principal, and the call reverts when it pays nothing — Unverified: the blocking state requires 32 consecutive positions that remain non-paying at the list head.
- **A borrower cannot repay during an oracle outage** — `src/vault_engine.vy.repay` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: `repay` calls `_checked_rate()` before accruing debt or burning BOBC although repayment does not use collateral value — Unverified: whether the oracle can stop publishing beyond the configured 3,600-second freshness window is unknown.
- **A borrower cannot lower future interest during an oracle outage** — `src/vault_engine.vy.set_rate` · seen in 1/3 runs · NEW · [agents: 5] — Code smells: the function calls `_checked_rate()` before changing the annual rate but does not use the returned value — Unverified: whether oracle downtime should block rate reductions is a protocol policy question.

---

> ⚠️ This review was performed by an AI assistant. AI analysis can never verify the complete absence of vulnerabilities and no guarantee of security is given. Team security reviews, bug bounty programs, and on-chain monitoring are strongly recommended. For a consultation regarding your projects' security, visit [https://www.pashov.com](https://www.pashov.com)
