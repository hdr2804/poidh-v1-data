#!/usr/bin/env python3
"""poidh v1 (Arbitrum) per-wallet extraction — bounty #1497.

Independent implementation: reads POIDHNFT contract state directly via eth_call
against a public Arbitrum RPC, pinned to one block. No indexers, no keys.

Contract: 0xdffe8a4a4103f968ffd61fd082d08c41dcf9b940 (poidh v1, Arbitrum One)

Definitions (from the bounty spec):
- eth_paid_out[wallet]  = sum of amounts of COMPLETED bounties issued by wallet
  (completed = a claim was accepted, i.e. bounty.claimer != 0x0 and amount > 0)
- eth_earned[wallet]    = sum of amounts of completed bounties won by wallet,
  GROSS (full bounty amount, protocol's 2.5% fee NOT deducted, per spec)
- v1_nfts_held[wallet]  = current count of poidh v1 NFTs owned (ERC721Enumerable)
Wallet universe = every wallet that interacted: bounty issuers, claim submitters,
winners, and current NFT holders.
"""
import json, sys, time, csv, collections, urllib.request
from decimal import Decimal
from eth_abi import encode, decode
from eth_utils import keccak, to_checksum_address

RPC = "https://arb1.arbitrum.io/rpc"
C = "0xdffe8a4a4103f968ffd61fd082d08c41dcf9b940"
ZERO = "0x0000000000000000000000000000000000000000"

def sel(sig):
    return "0x" + keccak(text=sig)[:4].hex()

import subprocess

def _post(payload):
    p = subprocess.run(["curl", "-s", "-X", "POST", RPC, "-H", "Content-Type: application/json",
                        "-H", "User-Agent: Mozilla/5.0", "-d", json.dumps(payload)],
                       capture_output=True, text=True, timeout=120)
    return json.loads(p.stdout)

def rpc_batch(calls, block):
    body = [{"jsonrpc": "2.0", "id": i, "method": "eth_call",
             "params": [{"to": C, "data": d}, block]} for i, d in enumerate(calls)]
    for attempt in range(6):
        try:
            out = _post(body)
            if isinstance(out, dict):
                out = [out]
            out = sorted(out, key=lambda x: x["id"])
            return [o.get("result") for o in out]
        except Exception as e:
            print("rpc retry", attempt, str(e)[:90], file=sys.stderr, flush=True)
            time.sleep(2 + attempt * 3)
    raise SystemExit("RPC failed permanently")

def rpc_one(method, params):
    return _post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})["result"]

BLOCK = rpc_one("eth_blockNumber", [])
BLOCK_N = int(BLOCK, 16)
print("pinned block:", BLOCK_N, file=sys.stderr, flush=True)

def call1(sig, types=(), args=()):
    data = sel(sig) + (encode(list(types), list(args)).hex() if types else "")
    return rpc_batch([data], BLOCK)[0]

n_bounties = decode(["uint256"], bytes.fromhex(call1("getBountiesLength()")[2:]))[0]
supply = decode(["uint256"], bytes.fromhex(call1("totalSupply()")[2:]))[0]
print("bounties:", n_bounties, "| nft supply:", supply, file=sys.stderr, flush=True)

BT = "(uint256,address,string,string,uint256,address,uint256,uint256)"
bounties = []
step = 5
for s in range(0, n_bounties, step):
    e = min(n_bounties - 1, s + step - 1)
    res = rpc_batch([sel("getBounties(uint256,uint256)") + encode(["uint256", "uint256"], [s, e]).hex()], BLOCK)[0]
    if not res:
        raise SystemExit(f"getBounties {s}-{e} failed")
    for b in decode([BT + "[]"], bytes.fromhex(res[2:]))[0]:
        bounties.append({"id": b[0], "issuer": to_checksum_address(b[1]), "amount": b[4],
                         "claimer": to_checksum_address(b[5])})
    print("bounties read:", len(bounties), file=sys.stderr, flush=True)

paid, earned = collections.Counter(), collections.Counter()
n_issued, n_won = collections.Counter(), collections.Counter()
wallets = set()
completed = cancelled = 0
for b in bounties:
    wallets.add(b["issuer"])
    if b["claimer"] != ZERO and b["amount"] > 0:
        completed += 1
        paid[b["issuer"]] += b["amount"]; n_issued[b["issuer"]] += 1
        earned[b["claimer"]] += b["amount"]; n_won[b["claimer"]] += 1
        wallets.add(b["claimer"])
    elif b["amount"] == 0:
        cancelled += 1

CT = ["uint256", "address", "uint256", "address", "string", "string", "uint256", "uint256"]
submitters = set()
for s in range(0, supply, 25):
    res = rpc_batch([sel("claims(uint256)") + encode(["uint256"], [i]).hex()
                     for i in range(s, min(supply, s + 25))], BLOCK)
    for r in res:
        if r and len(r) > 2:
            submitters.add(to_checksum_address(decode(CT, bytes.fromhex(r[2:]))[1]))
    print("claims read:", min(supply, s + 25), file=sys.stderr, flush=True)
wallets |= submitters

held = collections.Counter()
token_ids = []
for s in range(0, supply, 25):
    res = rpc_batch([sel("tokenByIndex(uint256)") + encode(["uint256"], [i]).hex()
                     for i in range(s, min(supply, s + 25))], BLOCK)
    token_ids += [decode(["uint256"], bytes.fromhex(r[2:]))[0] for r in res]
for s in range(0, len(token_ids), 25):
    res = rpc_batch([sel("ownerOf(uint256)") + encode(["uint256"], [t]).hex()
                     for t in token_ids[s:s + 25]], BLOCK)
    for r in res:
        owner = to_checksum_address("0x" + r[-40:])
        held[owner] += 1
        wallets.add(owner)
    print("owners read:", min(len(token_ids), s + 25), file=sys.stderr, flush=True)

def eth(wei):
    return format((Decimal(wei) / Decimal(10) ** 18).normalize(), "f")

wallets.discard(to_checksum_address(C))  # the contract itself is not a user wallet (it custodies unclaimed claim NFTs)
rows = []
for w in sorted(wallets, key=lambda x: x.lower()):
    rows.append({"wallet": w, "eth_paid_out": eth(paid.get(w, 0)), "eth_earned": eth(earned.get(w, 0)),
                 "v1_nfts_held": held.get(w, 0), "bounties_completed_issued": n_issued.get(w, 0),
                 "bounties_won": n_won.get(w, 0)})

with open("poidh_v1_wallets.csv", "w", newline="") as f:
    wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    wtr.writeheader(); wtr.writerows(rows)

summary = {"chain": "arbitrum-one", "contract": C, "block": BLOCK_N,
           "bounties": n_bounties, "completed": completed, "cancelled": cancelled,
           "nft_supply": supply, "wallets": len(rows), "claim_submitters": len(submitters),
           "holders": len([h for h in held if h != to_checksum_address(C)]),
           "nfts_in_contract_pending": held.get(to_checksum_address(C), 0),
           "total_paid_out_eth": eth(sum(paid.values())), "total_earned_eth": eth(sum(earned.values()))}
with open("summary.json", "w") as f:
    json.dump(summary, f, indent=1)
print(json.dumps(summary, indent=1))
