"""Record a deterministic settlement run to docs/run.json.

This drives the offline NEAR client through a full market lifecycle: open,
three stakes on opposite sides, resolve after close, and settle every winner
pro rata with the last-winner dust sweep. The output is a trace of real
settlement arithmetic (the same math the Rust contract runs), not a hand-typed
mock, so the UI renders a genuine execution.

Run: python scripts/record_run.py
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from settlemint.model import Outcome  # noqa: E402
from settlemint.near import OfflineNearClient  # noqa: E402

# One NEAR is 1e24 yoctoNEAR. We use whole-NEAR stakes that do not divide
# evenly, so the dust sweep is visibly exercised.
NEAR = 10**24
CLOSE_NS = 2_000_000_000_000_000_000  # an arbitrary fixed block timestamp
RESOLVER = "resolver.testnet"


def record() -> dict:
    c = OfflineNearClient()

    event_id = c.create_event(RESOLVER, CLOSE_NS, now_ns=CLOSE_NS - 1)

    # Yes side: two stakers that split 3 NEAR into an indivisible ratio.
    c.take_position(event_id, "alice.testnet", Outcome.YES, 2 * NEAR, CLOSE_NS - 1)
    c.take_position(event_id, "carol.testnet", Outcome.YES, 1 * NEAR, CLOSE_NS - 1)
    # No side: one loser.
    c.take_position(event_id, "bob.testnet", Outcome.NO, 2 * NEAR, CLOSE_NS - 1)

    # Resolver settles Yes, only legal at/after close.
    c.resolve(event_id, RESOLVER, Outcome.YES, now_ns=CLOSE_NS)

    # Settle every winner. Total pool is 5 NEAR; Yes pool is 3 NEAR.
    # alice: 5*2//3 = 3.333... NEAR; carol sweeps the remainder.
    pay_alice = c.settle(event_id, "alice.testnet")
    pay_carol = c.settle(event_id, "carol.testnet")

    ev = c.market.get_event(event_id)
    total_in = 5 * NEAR
    total_out = pay_alice + pay_carol

    return {
        "network": "offline-fixture (deterministic mirror of NEAR testnet flow)",
        "note": (
            "Produced by scripts/record_run.py against the offline NEAR client, "
            "which runs the same settlement arithmetic as contract/src/lib.rs. "
            "No key is shipped, so no public testnet receipt exists yet; the "
            "live backend targets NEAR testnet only."
        ),
        "contract": "settlemint (WASM built from contract/, 205 KB release)",
        "event_id": event_id,
        "resolver": RESOLVER,
        "final_event": ev,
        "conservation": {
            "total_staked_yocto": total_in,
            "total_paid_yocto": total_out,
            "balanced": total_in == total_out,
            "escrow_remaining": ev["escrow"],
        },
        "payouts": {
            "alice.testnet": pay_alice,
            "carol.testnet": pay_carol,
        },
        "steps": [dataclasses.asdict(s) for s in c.steps],
    }


def main() -> None:
    run = record()
    out = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "run.json"
    )
    with open(out, "w") as fh:
        json.dump(run, fh, indent=2)
    print(f"wrote {out}")
    print(
        f"conservation: staked={run['conservation']['total_staked_yocto']} "
        f"paid={run['conservation']['total_paid_yocto']} "
        f"balanced={run['conservation']['balanced']}"
    )


if __name__ == "__main__":
    main()
