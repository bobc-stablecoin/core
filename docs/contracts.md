# Reading the contracts

The pages before this one are the behavior. These are the files, in the order that matches that story.

## `src/bobc.vy`

The token. Snekmate provides the ERC-20 and permit surface. This file adds two functions, `mint` and `burn`, and both require the bound engine. Deployment calls `bind_vault_engine` once and then drops ownership. Nothing else in the protocol can create or destroy BOBC.

Read `bind_vault_engine`, `mint`, and `burn`. Then leave this file.

## `src/sorted_positions.vy`

The rate list from [Redemption](redemption.md). No balances and no oracle. `_insert` checks the caller's `prev` and `next`. `_remove` unlinks a borrower when a loan is closed or liquidated. `_head` is who gets redeemed first.

## `src/vault_engine.vy`

Read it in this order:

1. `open_position` — pull crvUSD, deposit to LlamaLend, require the minimum ratio, mint the debt, link the rate.
2. `_accrue` — add interest to `debt` and `fees`, and mint that BOBC to the engine. Every state-changing call on a position accrues it first.
3. `withdraw_collateral` — LlamaLend yield leaving, stopped at the minimum ratio.
4. `redeem` and `_redeem_from` — walk from the head, skip anything under the liquidation ratio, burn the caller's principal, return leftover shares to the borrower.
5. `liquidate` and `_payout` — the 120% line, the 4% / 1% split, insurance, and `bad_debt`.
6. `close_position` — burn principal from the borrower, burn `fees` from the engine, return the shares.

`set_rate` is the unlink-and-insert used to move in the list. `repay` burns principal and refuses to leave dust below the debt floor. `collateral_ratio` includes interest that has not been written yet, and it uses the same oracle freshness check as the state-changing calls.

`_checked_rate` is the whole oracle gate: non-zero, not in the future, not older than `MAX_STALENESS`.

## `src/cashback.vy`

Not part of minting or solvency. `pay` moves the payer's BOBC to a receiver and then rebates the payer from BOBC this contract already holds. If the rebate balance is empty, the whole payment reverts. The engine does not premint that inventory. Someone has to transfer BOBC in.

## What not to look for

There is no pooled `mint` that turns crvUSD into BOBC at the full oracle rate. There is no function that freezes every holder because the oracle left a band around one BOB per USD. There is no LLAMMA position. Collateral is crvUSD shares in the lender vault, and the risk that moves the ratio is the BOB-per-USD rate plus whatever that vault does to the share price.
