# BOBC Fyzz campaign report

## Scope and environment

The stateful suite exercises the production BOBC, Cashback, VaultEngine, and
sorted-position behavior locally through Moccasin and Titanoboa. Each machine
instance deploys mock crvUSD, an ERC-4626 vault, and a peg oracle, then deploys
the three production contracts, binds BOBC to VaultEngine, and funds isolated
borrowers, holders, liquidators, the owner, and merchants. Boa anchors isolate
the EVM state; dedicated tests check fresh state across instances and cleanup
after failed initialization.

| Tool | Version |
| --- | --- |
| Python | 3.13.3 |
| Vyper | 0.4.3 |
| Moccasin | 0.4.4 |
| Titanoboa | 0.2.8 |
| Hypothesis | 6.168.0 |
| pytest | 9.1.1 |

The helper inventory in `contracts.json` was generated from compiled Moccasin
artifacts under `out/`; production constructors and callable ABIs were checked
against the Vyper sources. Bounds not represented in the ABI, including the
merchant array capacity and redemption's 32-node traversal, were checked in the
source. Local mocks deliberately model mutable oracle samples and vault share
value. They do not establish the configured Arbitrum vault's liquidity,
withdrawal, loss, or token behavior.

## Campaigns and commands

The smoke profile used 10 examples × 20 stateful steps. It established action
reachability before the bounded campaign. The standard profile used 100
examples × 50 steps, no per-example deadline, and Hypothesis seed `20260927`.
The successful standard run is
`runs/20260927T213025-1790559025759036000/`: 157.40 seconds, exit code 0, no
property failures. This records **no violation found in this run**, not a proof
of safety.

```sh
FYZZ_PROFILE=smoke uv run mox test tests/fuzz -q
uv run python3 /Users/rabuawad/.agents/skills/fyzz/scripts/fyzz.py \
  --framework moccasin --suite-dir tests/fuzz --meta-dir fuzz_data \
  --runner '["uv","run","mox","test"]' \
  --seed 20260927 run . --profile standard
FYZZ_PROFILE=smoke uv run mox test -q
FYZZ_PROFILE=smoke uv run mox test --coverage -q
```

Successful standard-campaign reachability included 260 opens, 70 collateral
additions, 37 withdrawals, 28 additional borrows, 40 repayments, 7 closes, 68
rate changes, 30 redemptions, 51 liquidations, 404 BOBC transfers, and 141
Cashback payments. It also completed funding, approval, merchant replacement,
merchant add/remove/clear, ownership transfer and acceptance, oracle updates,
vault yield/loss changes, and time travel. The stateful harness recorded 106
reachability examples including shrinking and replay.

Expected rejection actions also executed: 119 over-limit Cashback rates, 10
empty-inventory payments, 31 stale-oracle additions, 72 final-principal
repayments that would leave fee-only nodes, 388 inadequate-collateral-balance
additions, 76 invalid list hints, 48 unauthorized Cashback admin calls, and
37 unauthorized mint calls. Each negative action checks the expected revert
reason and a relevant before/after state snapshot.

## Action selection and bounds

Primary actions are position open/add/withdraw/borrow/repay/close/rate change,
redemption, liquidation, BOBC transfers and approvals, and Cashback payment.
Secondary actions include Cashback funding and owner/merchant/rate changes,
ownership handoff, oracle changes, time travel, vault yield/loss, and deliberate
invalid-hint, stale-oracle, inadequate-balance, over-cap, empty-pool, unauthorized,
and final-principal repayment reverts. `selection.json` records the complete
selection.

Direct BOBC binding is deployment setup and occurs once per machine. Permit
signature and nonce cases remain deterministic tests because the stateful suite
does not generate signatures. Direct engine-only mint/burn operations are
exercised through the public position lifecycle. Constructor validation and
fork-only vault writes remain deterministic integration checks. Arbitrary
address fuzzing is excluded; address rules use generated modeled actors.

## Properties

`PROPERTIES.md` contains six implemented global properties and twenty
implemented action properties. The campaign reached the core accounting,
position/list ordering, repayment/redemption, liquidation, Cashback inventory,
merchant synchronization, ownership handoff, and negative-case hooks. GL-07,
the sum of every possible BOBC holder balance, remains exploratory because an
arbitrary external address can hold tokens. GL-08, real-vault redeemability,
remains pending because local mocks do not model the configured vault's
liquidity and integration behavior.

The final-principal repayment property covers the confirmed fee-only linked
position defect. `repay` now rejects repayment of all principal while the
position remains linked; the borrower can use `close_position` to remove the
node and return collateral. A deterministic test reproduces the fee-floor
condition and checks the revert leaves accounting unchanged.

## Harness failures and deterministic replays

An early stateful run generated debt using deposited assets before accounting
for ERC-4626 share rounding. In one trace, a deposit of 3,272 crvUSD minted
1,303.579109134353315146e18 shares that represented 3,271.999999999999999998
crvUSD; the two-wei shortfall made the generated debt fail the engine's minimum
collateral check. The prior standard attempt spent 331.53 seconds shrinking
before failing. The strategy now simulates the mock's deposit share minting and
post-deposit asset conversion, then leaves a two-wei debt cushion.
`tests/fuzz/test_strategy_regressions.py::test_open_strategy_accounts_for_share_price_rounding`
replays the exact supply, vault assets, deposit, oracle rate, and old failing
debt, then proves the corrected generated debt opens successfully.

A separate invalid-list-hint action also failed its intended revert check
because its naive debt crossed the collateral threshold first. The preserved
trace is in
`runs/20260927T191406-1790550846494581000/traces/6602335ef125467da6c9bfac85dcec8e.json`.
The dynamic debt strategy now reaches `List: bad hint`, and
`tests/fuzz/test_strategy_regressions.py::test_bad_hint_replay_accounts_for_vault_share_rounding`
reproduces the exact oracle sample and vault-yield-adjusted share conversion.
Both failures were harness strategy errors, not contract violations. The
Hypothesis database, failed run traces, campaign logs, and successful run
artifacts remain under `fuzz_data/`.

## Coverage and remaining checks

The separate local Vyper-attributed coverage run reported 100% for
`src/bobc.vy`, 91% for `src/cashback.vy`, 79% for `src/sorted_positions.vy`,
and 89% for `src/vault_engine.vy`. These figures come from Moccasin's Vyper
source attribution; Python harness, mocks, deployment scripts, and dependencies
are excluded from the production-contract summary. Coverage does not replace
the property or integration checks.

The local suite skips the Arbitrum vault integration test unless
`ARBITRUM_RPC` is configured. `ARBITRUM_FORK_BLOCK` can pin a reproducible fork
block; otherwise the test uses the RPC's `safe` block tag. Real-vault withdrawal
limits, liquidity, losses, fee-on-transfer behavior, and exact deployed bytecode
remain unverified without that fork run. GL-07 and GL-08 are the remaining
stateful property gaps.
