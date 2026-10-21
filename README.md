# poidh v1 data — per-wallet CSV

Per-wallet extraction of the **poidh v1** protocol on Arbitrum One, built for
[poidh bounty #1497](https://poidh.xyz/base/bounty/1497).

**Contract:** `0xdffe8a4a4103f968ffd61fd082d08c41dcf9b940` (POIDHNFT, Arbitrum One)
**Snapshot block:** 516912665 — read straight from contract state with `eth_call`
against a public Arbitrum RPC. No indexer, no API keys. v1 is retired, so the
state is static.

## Download

**CSV (direct download):**
https://raw.githubusercontent.com/hdr2804/poidh-v1-data/main/poidh_v1_wallets.csv

## Columns

| column | meaning |
| --- | --- |
| `wallet` | every wallet that ever interacted with v1: bounty issuers, claim submitters, winners, current NFT holders |
| `eth_paid_out` | total ETH paid out for **completed** bounties issued by this wallet (full bounty amounts) |
| `eth_earned` | total ETH earned from completed bounties won by this wallet — **gross**, the 2.5% protocol fee is NOT deducted (a 1 ETH bounty win counts as 1 ETH, per the bounty spec) |
| `v1_nfts_held` | poidh v1 NFTs currently held (ERC721Enumerable ownership) |
| `bounties_completed_issued` | number of completed bounties issued |
| `bounties_won` | number of bounties won |

Definitions: a bounty is *completed* when a claim was accepted on-chain
(`claimer != 0x0`, amount > 0); a cancelled bounty has its amount zeroed by
`cancelBounty`. The contract address itself is excluded from the rows — it
custodies 444 unclaimed claim NFTs, reported in `summary.json` instead.

## Summary

- 496 bounties: 278 completed, 169 cancelled, 49 never resolved
- 722 v1 NFTs minted (claim NFTs), 80 wallets currently hold NFTs
- 414 unique wallets, 374 claim submitters
- Total paid out = total earned = **3.726923002 ETH**

Full numbers in [`summary.json`](summary.json).

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install eth-abi eth-utils "eth-hash[pycryptodome]"
.venv/bin/python extract.py   # writes poidh_v1_wallets.csv + summary.json
```

`extract.py` pins the current block, walks `getBounties`, every `claims(i)`,
and every NFT via `tokenByIndex`/`ownerOf`, then aggregates per wallet.
