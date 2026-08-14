"""A pure-Python mirror of the NEAR settlement core.

Every arithmetic decision here matches `contract/src/lib.rs` exactly: the same
four-phase lifecycle, the same resolver-only resolution, the same pro-rata
pari-mutuel payout with a last-winner dust sweep, and the same void escape
hatch. The parity tests pin this model against the values the Rust contract
produces, so a one-line drift in either side fails the suite.

Amounts are integer yoctoNEAR. There is no floating point anywhere in the
settlement path, exactly as on-chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Outcome(str, Enum):
    UNRESOLVED = "Unresolved"
    YES = "Yes"
    NO = "No"


class Phase(str, Enum):
    OPEN = "Open"
    RESOLVED = "Resolved"
    SETTLED = "Settled"
    VOIDED = "Voided"


# Seven days in nanoseconds, matching VOID_GRACE_NS in the contract.
VOID_GRACE_NS = 7 * 24 * 60 * 60 * 1_000_000_000


class SettlementError(Exception):
    """Raised with the same string the contract's `require!` would panic with."""


@dataclass
class _Event:
    resolver: str
    closes_at: int
    phase: Phase = Phase.OPEN
    outcome: Outcome = Outcome.UNRESOLVED
    pool_yes: int = 0
    pool_no: int = 0
    escrow: int = 0
    unclaimed_win_stake: int = 0
    yes_stake: dict = field(default_factory=dict)
    no_stake: dict = field(default_factory=dict)
    claimed: dict = field(default_factory=dict)


class EventMarket:
    """The settlement state machine, driven by a monotonically advancing clock.

    `now_ns` is passed into each mutating call the way a NEAR block timestamp is
    read inside a contract method, so the model is deterministic and needs no
    real wall clock.
    """

    def __init__(self) -> None:
        self._next_id = 0
        self._events: dict[int, _Event] = {}

    # --- lifecycle ---

    def create_event(self, resolver: str, closes_at: int, now_ns: int) -> int:
        if closes_at <= now_ns:
            raise SettlementError("ClosesInPast")
        event_id = self._next_id
        self._next_id += 1
        self._events[event_id] = _Event(resolver=resolver, closes_at=closes_at)
        return event_id

    def take_position(
        self, event_id: int, account: str, side: Outcome, amount: int, now_ns: int
    ) -> None:
        e = self._require(event_id)
        if e.phase != Phase.OPEN:
            raise SettlementError("NotOpen")
        if now_ns >= e.closes_at:
            raise SettlementError("MarketClosed")
        if amount <= 0:
            raise SettlementError("ZeroStake")
        if side == Outcome.YES:
            e.yes_stake[account] = e.yes_stake.get(account, 0) + amount
            e.pool_yes += amount
        elif side == Outcome.NO:
            e.no_stake[account] = e.no_stake.get(account, 0) + amount
            e.pool_no += amount
        else:
            raise SettlementError("InvalidSide")
        e.escrow += amount

    def resolve(self, event_id: int, caller: str, outcome: Outcome, now_ns: int) -> None:
        e = self._require(event_id)
        if caller != e.resolver:
            raise SettlementError("NotResolver")
        if outcome not in (Outcome.YES, Outcome.NO):
            raise SettlementError("InvalidSide")
        if e.phase == Phase.VOIDED:
            raise SettlementError("MarketVoided")
        if e.phase != Phase.OPEN:
            raise SettlementError("AlreadyResolved")
        if now_ns < e.closes_at:
            raise SettlementError("MarketStillOpen")
        e.phase = Phase.RESOLVED
        e.outcome = outcome
        e.unclaimed_win_stake = e.pool_yes if outcome == Outcome.YES else e.pool_no

    def void_event(self, event_id: int, now_ns: int) -> None:
        e = self._require(event_id)
        if e.phase != Phase.OPEN:
            raise SettlementError("NotOpen")
        if now_ns < e.closes_at + VOID_GRACE_NS:
            raise SettlementError("VoidTooEarly")
        e.phase = Phase.VOIDED

    def payout_of(self, event_id: int, account: str) -> int:
        e = self._require(event_id)
        return self._payout_inner(e, account)

    def _payout_inner(self, e: _Event, account: str) -> int:
        if e.phase == Phase.OPEN:
            return 0
        if e.claimed.get(account, False):
            return 0
        yes = e.yes_stake.get(account, 0)
        no = e.no_stake.get(account, 0)
        if e.phase == Phase.VOIDED:
            return yes + no
        win_pool = e.pool_yes if e.outcome == Outcome.YES else e.pool_no
        if win_pool == 0:
            return yes + no
        mine = yes if e.outcome == Outcome.YES else no
        if mine == 0:
            return 0
        if mine >= e.unclaimed_win_stake:
            return e.escrow  # last winner sweeps the remainder (dust included)
        total = e.pool_yes + e.pool_no
        return (total * mine) // win_pool

    def settle(self, event_id: int, account: str) -> int:
        e = self._require(event_id)
        if e.phase == Phase.OPEN:
            raise SettlementError("NotResolved")
        if e.claimed.get(account, False):
            raise SettlementError("AlreadyClaimed")
        payout = self._payout_inner(e, account)
        if payout == 0:
            raise SettlementError("NothingToClaim")
        e.claimed[account] = True
        if e.phase == Phase.RESOLVED:
            mine = (
                e.yes_stake.get(account, 0)
                if e.outcome == Outcome.YES
                else e.no_stake.get(account, 0)
            )
            if mine > e.unclaimed_win_stake:
                mine = e.unclaimed_win_stake
            e.unclaimed_win_stake -= mine
        e.escrow -= payout
        if e.escrow == 0 and e.phase == Phase.RESOLVED:
            e.phase = Phase.SETTLED
        return payout

    # --- views ---

    def get_event(self, event_id: int) -> dict:
        e = self._require(event_id)
        return {
            "resolver": e.resolver,
            "closes_at": e.closes_at,
            "phase": e.phase.value,
            "outcome": e.outcome.value,
            "pool_yes": e.pool_yes,
            "pool_no": e.pool_no,
            "escrow": e.escrow,
            "unclaimed_win_stake": e.unclaimed_win_stake,
        }

    def liability_of(self, event_id: int) -> tuple[int, int]:
        e = self._require(event_id)
        return e.escrow, e.unclaimed_win_stake

    def is_voidable(self, event_id: int, now_ns: int) -> bool:
        e = self._events.get(event_id)
        if e is None:
            return False
        return e.phase == Phase.OPEN and now_ns >= e.closes_at + VOID_GRACE_NS

    @property
    def next_event_id(self) -> int:
        return self._next_id

    def _require(self, event_id: int) -> _Event:
        e = self._events.get(event_id)
        if e is None:
            raise SettlementError("UnknownEvent")
        return e
