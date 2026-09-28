# Fyzz property implementation plan

## Priority and modeled relations

Amounts below use 18-decimal wei unless stated otherwise; rates, ratios, and
oracle values use WAD (`1e18`), BPS use 10,000, and time uses seconds. `SHOULD`
marks a code/documented guarantee; `EXP` marks an exploratory expectation.

| ID | Priority | Relation or postcondition | Evidence / domain |
| --- | --- | --- | --- |
| GL-01 | P0 | `BOBC.totalSupply = total_debt + bad_debt` | Engine accounting and liquidation docs |
| GL-02 | P0 | `BOBC.balanceOf(engine) = surplus` | `_accrue`, fee burn, and close paths |
| GL-03 | P0 | `Σ listed debt = total_debt`; `Σ listed shares = total_shares`; list is acyclic, rates are nondecreasing, and linked `debt > fees` | Engine position storage and sorted list |
| GL-04 | P1 | `ASSET.balanceOf(engine) = insurance_assets` | Insurance custody; excludes direct unmodeled donations |
| GL-05 | P1 | `set(MERCHANTS) = modeled approved set`; `is_merchant(a) = (a in set)` | Owner merchant operations |
| GL-06 | P1 | On-chain `owner` and `pending_owner` equal the independent handoff model | Two-step ownership exports |
| GL-07 | P1 / EXP | Sum of balances over every possible address equals `totalSupply` | Exploratory: state machine only enumerates modeled and protocol addresses |
| GL-08 | P0 / EXP | Real-vault share value is redeemable through the configured external vault | Exploratory: liquidity, loss, transfer, and withdrawal constraints need the fork |
| SP-01 | P0 | Open: position debt and borrower BOBC increase by `debt`; returned shares are positive | `open_position`; ERC-4626 conversion may floor assets |
| SP-02 | P1 | Add: `shares_after > shares_before`; borrower crvUSD decreases by the input amount | `add_collateral`; current share-price model |
| SP-03 | P0 | After withdrawal, `collateral_ratio >= MIN_CR` | Oracle-fresh withdrawal and pending interest |
| SP-04 | P0 | Borrow: `debt_after = debt_before + pending_interest + amount`; borrower BOBC increases by `amount` | `borrow` and `_accrue` |
| SP-05 | P0 | Repay: `debt_after = debt_before + pending_interest - amount`; `fees_after = fees_before + pending_interest`; caller BOBC falls by `amount` | `repay`, constrained to leave linked principal |
| SP-06 | P0 | Close: position exists flag, debt, fees, and shares clear; borrower receives current represented assets | `_clear_position` and full vault redemption |
| SP-07 | P1 | Rate after update equals requested rate; GL-03 checks reinsertion order | `set_rate` |
| SP-08 | P1 | Transfer preserves supply; sender falls and receiver rises by `amount` | BOBC ERC-20 transfer |
| SP-09 | P1 | Funding preserves BOBC total supply | Preminted inventory transfer |
| SP-10 | P1 | `rebate = floor(amount * BPS / 10,000)`; merchant gets amount; payer gets rebate; inventory falls by rebate; supply is unchanged | Cashback payment; positive rounded rebate |
| SP-11 | P1 | Unauthorized mint reverts and leaves supply and receiver balance unchanged | Bound engine is the only mint caller |
| SP-12 | P1 | Stale-oracle collateral addition reverts without changing position or balances | Current oracle gate policy |
| SP-13 | P1 | Nonadjacent/unlinked insertion hints revert without changing debt or supply | Sorted-list hint checks |
| SP-14 | P1 | `BPS > 200` reverts without changing configured BPS | Cashback policy cap |
| SP-15 | P1 | Nonowner configuration reverts without changing BPS | Cashback owner gate |
| SP-16 | P1 | Empty rebate inventory reverts payment and preserves balances and allowance | Cashback payment atomicity |
| SP-17 | P0 | `principal_before - principal_after = BOBC_burned`; surviving debt respects `MIN_DEBT`; assigned shares fall and redemption returns assets | Redemption; caller may be a position borrower and receive residual shares |
| SP-18 | P0 | Liquidation payout, caller burn, fee burn, insurance, borrower remainder, and bad debt equal independently calculated branch results | Solvent and underwater `_payout` paths |
| SP-19 | P1 | Insufficient crvUSD balance reverts and preserves position, wallet, vault, accounting, and supply snapshots | `add_collateral` transfer failure |
| SP-20 | P0 | If fees reach `MIN_DEBT`, repaying final principal reverts with no state changes; listed positions retain `debt > fees` | `repay`; borrower uses `close_position` to unlink |

The table records test priorities, not economic-policy changes. Any newly inferred
guarantee remains exploratory until product intent and external assumptions are
confirmed.

## Accepted guarantees

The six global properties GL-01 through GL-06 are invariants over every machine step. Their checks read the public BOBC, Engine, Cashback, and exported ownership state and compare it with either arithmetic identities or an independent Python model. They are wired in `tests/fuzz/properties.py` and listed with source evidence in `PROPERTIES.md`.

Action properties SP-01 through SP-10 compare successful calls with captured before-state and values supplied to those calls. Rejected cases SP-11 through SP-16 are explicit rules that require the expected Vyper error and compare a relevant state snapshot before and after. No broad exception handler can satisfy a negative case.

## Implemented after the initial smoke cycle

- **SP-17:** The redemption postcondition captures holder BOBC, borrower crvUSD, returned assets, position debt and shares, and the emitted redemption event. It checks principal burn, debt/share reduction, floor behavior, and touched positions using integer floor conversions and the 32-node limit. Sixty-four successful redemptions reached this hook in the standard campaign.
- **SP-18:** The liquidation postcondition independently calculates both payout branches from pre-call debt/fees, current share value, oracle rate, insurance, and penalty parameters. It checks liquidator BOBC burn, fee burn, insurance in/out, borrower payout, bad-debt delta, position removal, and supply accounting. Sixty-two liquidations reached this hook in the standard campaign.
- **SP-19:** An explicit low-crvUSD-balance action expects the transfer failure and checks that position, wallet, vault, debt, shares, fee surplus, and BOBC supply remain unchanged.
- **SP-20:** A final-principal repayment action accrues enough fees to reach the debt floor, then verifies the repayment reverts without state changes. GL-03 also checks that listed positions retain positive principal.

These remain unchecked until an assertion, action hook, and successful execution appear in reachability evidence. Do not infer coverage from the presence of decorators or source markers.

## Additional work after initial campaigns

1. Keep successful reachability for every selected primary action and lifecycle transition in future campaigns; zero successes means that campaign is incomplete.
2. Preserve the two-instance isolation tests: compare deployment addresses, balances, time, and model state across consecutive machine instances, and force an initialization exception to verify anchor cleanup.
3. Add any new negative cases with exact Vyper errors and state snapshots before marking their properties implemented.
4. Reconfirm the ABI inventory and source bounds after any production signature or bound changes.
