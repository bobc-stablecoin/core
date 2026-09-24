# Redemption

A holder who wants crvUSD burns BOBC and pulls crvUSD from somebody's position at the oracle. One BOBC takes `1 / oracle` crvUSD. At 13 BOB per USD, 1,000 BOBC takes `1,000 / 13 = 76.92` crvUSD.

The engine does not pick a position at random, and it does not pick the one that was minted with those particular tokens. BOBC is fungible. Once Alice spends hers, the token and her collateral are no longer tied together. The walk always starts at the lowest annual rate.

## Why anyone pays more than 0.5%

The cheap loan is the first one a redemption shrinks. The expensive loan is last.

Alice charges 0.5%, Bob 2%, Dan 8%. Each has locked 1,098.90 crvUSD and owes 10,000 BOBC, oracle at 13. A holder burns 1,000 BOBC:

- Alice gives up 76.92 crvUSD. Her debt falls to 9,000. She has 1,021.98 crvUSD left.
- Her ratio rises from 142.9% to `1,021.98 * 13 / 9,000 = 147.6%`.
- Bob and Dan are untouched.

She loses the LlamaLend yield on the 76.92 crvUSD, and she loses the size of the loan she wanted. She pays no penalty. The cushion stays with her. That is the whole cost of having chosen the cheap rate.

Dan pays 8% so this walk reaches him last. While nobody is redeeming, he is overpaying and, as [Positions](positions.md) showed, he may not be able to withdraw yield. When redemptions start, Alice's loan shrinks and his does not. If nobody is redeeming, borrowers lower their rates. If redemptions pick up, the cheap loans raise their rates and move back in the list.

Minting in order to redeem is a loss. Opening a loan locks about 143 BOB of crvUSD for every 100 BOBC, and redemption only returns 100. The caller has to already hold BOBC and prefer the crvUSD.

## A redemption that crosses three loans

The same three positions. A holder burns 25,000 BOBC.

Alice's whole 10,000 is taken first. That pulls `10,000 / 13 = 769.23` crvUSD. The other **329.67 crvUSD** is her cushion, and it is returned to her. Her loan is removed from the list. Bob is closed the same way and also receives 329.67 crvUSD.

Dan covers the last 5,000. He gives up 384.62 crvUSD, keeps 714.29 crvUSD, and still owes 5,000 BOBC. His ratio rises to `714.29 * 13 / 5,000 = 185.7%`.

If the requested amount would leave a position under the minimum debt (and the leftover is not just unpaid interest), the engine either takes the whole principal or stops where the remainder is still at least that floor. A redemption that finds nothing to take reverts. The call is capped by `max_iterations`, so one transaction cannot walk an unlimited list.

Positions already under the 120% liquidation ratio are skipped. Those are for `liquidate`, not for this walk.

## The ordered list

`src/sorted_positions.vy` does not hold collateral or debt. It is the line of borrowers, lowest rate at the head:

```text
head                                                tail
0.5% Alice  <->  2% Bob  <->  2% Dan's neighbor  <->  8% Dan
```

The engine can load Alice's position in one read. That read does not know whether her rate is the lowest one open. The head of this list is that answer.

Inserting by scanning from the head would grow with the number of loans. `open_position` and `set_rate` take the two neighbors the new node should sit between. The module checks that those neighbors currently point at each other, and that the new rate belongs between their rates. A stale hint reverts. The same rate keeps the order the hints choose. A forward walk that treats "rate less than or equal" as "already passed" inserts after existing equals.

Closing or liquidating unlinks that node. Changing rate is an unlink plus an insert, so the hints must describe the list as it will be after this borrower is removed.

Next: [Liquidation](liquidation.md). In the contracts, read `sorted_positions.vy`, then `redeem` and `_redeem_from`.
