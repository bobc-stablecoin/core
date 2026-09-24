# bobc-core

BOBC is a fully reserved stablecoin protocol for Arbitrum One, written in Vyper and built with
[Moccasin](https://github.com/Cyfrin/moccasin).

**This is a reserve vault, not a CDP.** A user deposits crvUSD, the engine supplies it to the Curve LlamaLend
ERC-4626 lender vault, and BOBC is minted at the PegOracle rate. BOBC users do not borrow, post collateral, or face
LLAMMA liquidation or soft-liquidation.

The target is 1 BOBC ≈ 1 BOB. The peg is live oracle pricing plus full-reserve redemption and arbitrage. BOBC below
fair value can be bought and redeemed for crvUSD; BOBC above fair value can be minted from crvUSD and sold. V1
assumes crvUSD ≈ USD.

## Contracts

- `src/bobc.vy`: composes Snekmate's ERC-20/EIP-2612 modules. Only the bound VaultEngine can mint or burn.
- `src/vault_engine.vy`: lender-side ERC-4626 deposits and withdrawals, oracle guards, TVL cap, and buffer solvency.
- `src/cashback.vy`: transfers payments and rebates from finite, preminted BOBC. It has no mint role.

The engine stores the optional `CASHBACK` deployment address. The PegOracle implementation lives in a sibling repository.

## Arbitrum One addresses

| Piece | Address |
|---|---|
| LlamaLend lender vault | `0xeEaF2ccB73A01deb38Eca2947d963D64CfDe6A32` |
| crvUSD | `0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5` |
| PegOracle | Set `PEG_ORACLE_ADDRESS` from `bobc-cre` |

PegOracle exposes `latest() -> (uint256 rate, uint64 updated_at)`, with rate as 1e18-scaled BOB per USD. Deviation
is measured against 1e18. Mint and redeem both stop for a stale, future, zero, or out-of-band sample.

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

T12 uses the real vault and crvUSD contracts, funds a generated account only in fork state, and performs a small
deposit/withdraw round trip. No live transaction is broadcast.

## Deployment configuration

`script/deploy.py` expects:

```bash
export PEG_ORACLE_ADDRESS="0x..."       # required
export ARBITRUM_RPC="https://..."       # required for Arbitrum execution
export BUFFER_BPS="0"                   # choose after reserve policy review
export MAX_TVL_ASSETS="1000000000000000000000000"
export MAX_STALENESS="3600"
export MAX_DEVIATION_BPS="500"
export CASHBACK_BPS="100"               # 1%

uv run mox run deploy --network arbitrum-fork
```

The helper deploys BOBC, Cashback, and VaultEngine, then irreversibly binds the token's mint/burn role to the
engine. It does not automatically premint rewards: first supply reserve surplus to the engine's vault position,
then call the one-time `premint_cashback(amount)`.

### Buffer bootstrap invariant

The locked mint formula issues the full `assets * rate / 1e18`. When `BUFFER_BPS > 0`, a new deposit by itself
cannot satisfy haircut solvency; the deployment needs pre-existing reserve surplus. Cashback inventory must also
be fully backed. The engine checks both conditions atomically, and T6 covers the bootstrap.

`deployments/arbitrum.json` is a publication schema. Replace `null` contract addresses and transaction hashes only
after an actual deployment.

## Security status

Unaudited. The engine deliberately contains no borrowing, collateral positions, LLAMMA integration, liquidation,
or reward minting. See [DESIGN_BRIEF.md](./DESIGN_BRIEF.md) for the locked design and risk boundaries.

## License

AGPL-3.0-or-later.
