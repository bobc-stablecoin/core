# Protocol understanding for Fyzz

## Deployment and bindings

1. Deploy `MockERC20` as the 18 decimal crvUSD reserve asset.
2. Deploy `MockERC4626` for that asset and `MockPegOracle` at 1 BOB/USD.
3. Deploy production BOBC, then production Cashback bound to BOBC, then production VaultEngine bound to BOBC, vault, asset, oracle, and risk settings.
4. Call `BOBC.bind_vault_engine(engine)` once. This renounces BOBC ownership, so the test never tries to replace the minter.
5. Fund three borrowers with 20,000 crvUSD each and approve the engine; fund modeled liquidators, holders, and deployer with crvUSD for role separation. Cashback begins empty and owner-controlled. Each example deploys fresh contracts inside its own Boa anchor.

## Actors

- `deployer`: initial BOBC and Cashback deployer and Cashback owner.
- `borrowers[0..2]`: independently modeled position owners and debt recipients.
- `holders[0..1]`: redemption users; they can also receive BOBC through modeled transfers.
- `liquidators[0..1]`: callers for liquidation; they can receive BOBC through modeled transfers.
- `merchants[0..2]`: possible Cashback destinations. Owner handoff may transfer configuration authority to any modeled actor.

The state machine derives each actor address from a stable Boa test label. It updates the Python owner/pending-owner/merchant set only after successful state-changing owner calls. Contract integers use Vyper `uint256`; actor addresses come from compiled ABI inputs. User amounts are generated as 18-decimal integer values and remain below actor funding or protocol caps before calls.

## Dependencies and mock boundaries

- Production `BOBC`, `Cashback`, and `VaultEngine` are imported with Vyper-native Moccasin imports.
- The mocks in `tests/mocks/` implement exact-transfer ERC-20, immediate 1:1 ERC-4626 accounting (with donations/losses modeled by changing vault-held assets), and a mutable 18-decimal oracle.
- These mocks do not model fee-on-transfer tokens, asynchronous LlamaLend withdrawals, share withdrawal limits, vault callbacks, or a changing vault asset address. The fork test covers the deployed Arbitrum vault separately when `ARBITRUM_RPC` is configured.

## Candidate guarantees and sources

- BOBC supply equals live position debt plus uncovered liquidation bad debt: `src/vault_engine.vy:total_debt`, `bad_debt`; `src/bobc.vy` mint/burn exports.
- BOBC held by the engine equals accrued interest surplus: `_accrue`, `_burn_fee`, `surplus`.
- Position debt/share totals match the ascending-rate linked list: `Position`, `total_debt`, `total_shares`, and `src/sorted_positions.vy` link operations.
- Engine idle crvUSD is accounted as liquidation insurance: `insurance_assets`, `_payout`, `liquidate`.
- Cashback inventory is finite; payment uses a floored BPS rebate and performs transfer/rebate in one EVM transaction: `src/cashback.vy:pay`.
- Merchant array and membership mapping remain synchronized through add/remove/replace/clear: `src/cashback.vy` administration functions.
- Owner replacement is two step: exported Snekmate `ownable_2step` state and methods.
- Oracle values are 18-decimal rates; Engine rejects zero, future, and older-than-`MAX_STALENESS` samples at operations that call `_checked_rate`.
- ERC-4626 accounting assumes returned shares are positive for any accepted positive collateral deposit; the engine now checks this assumption in `_pull_deposit`.

## Test boundary and unresolved risks

The local suite checks contract accounting against independently captured pre-call values and successful action inputs. Hypothesis reachability logs are empirical and may count replay and shrinking attempts. The real vault's upgrade state, withdrawal behavior, and historical state are only checked on a configured fork. A clean bounded run is not a proof of protocol safety.
