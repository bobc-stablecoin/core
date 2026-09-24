# bobc-core

BOBC is a collateralized debt protocol for Arbitrum One, written in Vyper and built with
[Moccasin](https://github.com/Cyfrin/moccasin).

A borrower deposits crvUSD. The engine supplies it to the Curve LlamaLend ERC-4626 lender vault and
mints BOBC as that borrower's debt, capped by a minimum collateral ratio. One address has one position.
The target is 1 BOBC ≈ 1 BOB. Holders burn BOBC to redeem crvUSD at the live PegOracle rate from the
open position charging the lowest interest. A position below the liquidation ratio can be closed out by
a caller who burns its debt. There is no LLAMMA position and no parity band around 1 BOB per USD.

LlamaLend appreciation belongs to the borrower and can be withdrawn while the position stays at or above
the minimum ratio. Borrow interest grows the debt and is minted to the engine. That balance is burned
when the position is closed or liquidated. Repayment and redemption burn principal BOBC from the caller.
Supply equals outstanding debt plus bad debt recorded when a liquidation cannot cover the full debt.

A walk through the numbers, then a pointer into the Vyper, is in [docs/README.md](docs/README.md).

## Contracts

- `src/bobc.vy`: composes Snekmate's ERC-20/EIP-2612 modules. Only the bound VaultEngine can mint or burn.
- `src/vault_engine.vy`: per-address collateral, debt, interest, redemption, and liquidation.
- `src/sorted_positions.vy`: hint-checked list of borrowers in ascending annual-rate order.
- `src/cashback.vy`: transfers payments and rebates from BOBC it already holds. It has no mint role.

The PegOracle implementation lives in a sibling repository. Cashback inventory is a later transfer of
already-minted BOBC, not an engine premint.

## Arbitrum One addresses

| Piece | Address |
|---|---|
| LlamaLend lender vault | `0xeEaF2ccB73A01deb38Eca2947d963D64CfDe6A32` |
| crvUSD | `0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5` |
| PegOracle | Set `PEG_ORACLE_ADDRESS` from `bobc-cre` |

PegOracle exposes `latest() -> (uint256 rate, uint64 updated_at)`, with rate as 1e18-scaled BOB per USD.
Opening, adjusting, redeeming, and liquidating all stop for a stale, future, or zero sample. A fresh rate
outside any fixed band still updates collateral ratios.

## Development

Python 3.11+ and `uv` are recommended.

Snekmate is pinned to `0.1.2`, the release aligned with Vyper 0.4.3. Its ERC-20 module supplies transfers,
allowances, metadata, EIP-2612 permit, and EIP-5267 domain introspection; BOBC selectively exports those functions
and retains protocol-specific engine-gated mint and burn wrappers.

```bash
uv sync
uv run mox compile
uv run mox test -v
```

With a global Moccasin install, use `mox compile` and `mox test -v` directly. Unit tests use typed Vyper mocks in
`tests/mocks`. The Arbitrum fork test is skipped unless the RPC is present:

```bash
export ARBITRUM_RPC="https://..."
uv run mox test tests/forked/test_arbitrum_vault.py -v
```

T12 uses the real vault and crvUSD contracts, funds a generated account only in fork state, and opens then closes
a small position. No live transaction is broadcast.

## Deployment configuration

`script/deploy.py` expects:

```bash
export PEG_ORACLE_ADDRESS="0x..."       # required
export ARBITRUM_RPC="https://..."       # required for Arbitrum execution
export MIN_CR="1430000000000000000"     # 143%
export LIQ_CR="1200000000000000000"     # 120%
export PENALTY_BPS="500"                # 4% caller, 1% insurance
export MAX_COLLATERAL_ASSETS="1000000000000000000000000"
export MAX_STALENESS="3600"
export MIN_DEBT="1000000000000000000000"
export MIN_ANNUAL_RATE="5000000000000000"   # 0.5%
export MAX_ANNUAL_RATE="250000000000000000" # 25%
export CASHBACK_BPS="100"               # 1%

uv run mox run deploy --network arbitrum-fork
```

The helper deploys BOBC, Cashback, and VaultEngine, then irreversibly binds the token's mint/burn role to the
engine. It does not fund the cashback contract.

The minimum collateral ratio must sit above the liquidation ratio, and the liquidation ratio must leave room for
the penalty. `MIN_CR` of 143% is the 9.1-versus-13 borrow cushion: at 13 BOB per USD, 1,430 crvUSD supports
1,000 BOBC.

`deployments/arbitrum.json` is a publication schema. Replace `null` contract addresses and transaction hashes only
after an actual deployment.

## Security status

Unaudited. Borrowers take the BOB-per-USD move on their own collateral ratio. Redemption is the holder exit.
Liquidation, including the crvUSD insurance slice of the penalty, is the solvency path. A shortfall that insurance
cannot cover is stored as `bad_debt` and left in circulation.

## License

AGPL-3.0-or-later.
