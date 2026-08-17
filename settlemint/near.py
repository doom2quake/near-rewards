"""The NEAR adapter seam.

Milestone 1's on-chain surface is a NEAR-native Rust contract (see `contract/`).
This module is the thin client an operator would use to drive it. It has two
backends behind one interface:

* `LiveNearClient` talks to a real NEAR testnet over JSON-RPC when
  `NEAR_RPC_URL` and a signer account are configured. It never targets mainnet:
  the constructor refuses any RPC URL whose host is not a testnet endpoint.

* `OfflineNearClient` replays the deterministic settlement model in
  `model.py`, so the whole flow runs keyless for tests, CI, and the UI. It
  produces the same run fixture shape a live run would, so `docs/run.json` is a
  genuine execution trace of the settlement math, not a hand-written mock.

`build_client()` picks the backend from the environment. Only the offline
backend is exercised in this repo, because we ship no funded testnet key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .model import EventMarket, Outcome


_MAINNET_HINTS = ("mainnet", "rpc.mainnet.near.org")


@dataclass
class RunStep:
    """One recorded call in a settlement run, mirroring a NEAR RPC receipt."""

    method: str
    args: dict
    caller: str
    result: object
    note: str


class OfflineNearClient:
    """Keyless backend: drives the pure-Python settlement model.

    The clock is explicit (nanosecond block timestamps) so a recorded run is
    fully deterministic and reproducible on any machine with no network.
    """

    backend = "offline"

    def __init__(self) -> None:
        self.market = EventMarket()
        self.steps: list[RunStep] = []

    def create_event(self, resolver: str, closes_at: int, now_ns: int) -> int:
        event_id = self.market.create_event(resolver, closes_at, now_ns)
        self.steps.append(
            RunStep(
                "create_event",
                {"resolver": resolver, "closes_at": closes_at},
                "creator.testnet",
                event_id,
                "open a Yes/No market with a named resolver",
            )
        )
        return event_id

    def take_position(
        self, event_id: int, account: str, side: Outcome, amount: int, now_ns: int
    ) -> None:
        self.market.take_position(event_id, account, side, amount, now_ns)
        self.steps.append(
            RunStep(
                "take_position",
                {"event_id": event_id, "side": side.value, "deposit": amount},
                account,
                None,
                f"{account} stakes {amount} yocto on {side.value}",
            )
        )

    def resolve(self, event_id: int, caller: str, outcome: Outcome, now_ns: int) -> None:
        self.market.resolve(event_id, caller, outcome, now_ns)
        self.steps.append(
            RunStep(
                "resolve",
                {"event_id": event_id, "outcome": outcome.value},
                caller,
                None,
                f"resolver records outcome {outcome.value} (only after close)",
            )
        )

    def settle(self, event_id: int, account: str) -> int:
        payout = self.market.settle(event_id, account)
        self.steps.append(
            RunStep(
                "settle",
                {"event_id": event_id, "account": account},
                "operator.testnet",
                payout,
                f"pay {account} their pro-rata share ({payout} yocto)",
            )
        )
        return payout

    def void_event(self, event_id: int, now_ns: int) -> None:
        self.market.void_event(event_id, now_ns)
        self.steps.append(
            RunStep(
                "void_event",
                {"event_id": event_id},
                "anyone.testnet",
                None,
                "resolver never showed; anyone voids after the grace window",
            )
        )


class LiveNearClient:
    """Real testnet backend (never constructed without explicit creds).

    Testnet only: the constructor rejects any RPC URL that looks like mainnet.
    This backend is present as the adapter seam milestone 3 fills in; milestone
    1 ships it guarded and unused rather than pretending it ran.
    """

    backend = "live"

    def __init__(self, rpc_url: str, signer: str) -> None:
        host = rpc_url.lower()
        if any(h in host for h in _MAINNET_HINTS):
            raise ValueError(
                "LiveNearClient refuses mainnet; this project is testnet only"
            )
        if "testnet" not in host:
            raise ValueError(
                "NEAR_RPC_URL must be a testnet endpoint (contains 'testnet')"
            )
        self.rpc_url = rpc_url
        self.signer = signer

    def _unavailable(self, *_a, **_k):  # pragma: no cover - not exercised keyless
        raise RuntimeError(
            "LiveNearClient is a milestone-3 seam; no funded testnet key is "
            "shipped, so no live call is made in this repo"
        )

    create_event = take_position = resolve = settle = void_event = _unavailable


def build_client() -> object:
    """Pick a backend from the environment.

    Returns a `LiveNearClient` only when `NEAR_RPC_URL` and `NEAR_SIGNER` are
    both set; otherwise the keyless offline backend.
    """
    rpc = os.environ.get("NEAR_RPC_URL")
    signer = os.environ.get("NEAR_SIGNER")
    if rpc and signer:
        return LiveNearClient(rpc, signer)
    return OfflineNearClient()
