"""Behaviour of the Python settlement model.

These mirror, name for name, the Rust unit tests in contract/src/lib.rs, so the
two implementations are checked against the same lifecycle rules.
"""

import pytest

from settlemint.model import (
    VOID_GRACE_NS,
    EventMarket,
    Outcome,
    Phase,
    SettlementError,
)

CLOSE = 1_000_000


def open_market(resolver="r.near"):
    m = EventMarket()
    eid = m.create_event(resolver, CLOSE, now_ns=0)
    return m, eid


def test_create_assigns_sequential_ids():
    m = EventMarket()
    assert m.create_event("r.near", CLOSE, 0) == 0
    assert m.create_event("r.near", CLOSE, 0) == 1
    assert m.next_event_id == 2


def test_create_rejects_past_close():
    m = EventMarket()
    with pytest.raises(SettlementError, match="ClosesInPast"):
        m.create_event("r.near", 400, now_ns=500)


def test_take_position_accumulates_pools():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    m.take_position(eid, "alice.near", Outcome.YES, 50, 20)
    m.take_position(eid, "bob.near", Outcome.NO, 30, 30)
    e = m.get_event(eid)
    assert e["pool_yes"] == 150
    assert e["pool_no"] == 30
    assert e["escrow"] == 180


def test_take_position_rejects_zero():
    m, eid = open_market()
    with pytest.raises(SettlementError, match="ZeroStake"):
        m.take_position(eid, "alice.near", Outcome.YES, 0, 10)


def test_take_position_rejects_after_close():
    m, eid = open_market()
    with pytest.raises(SettlementError, match="MarketClosed"):
        m.take_position(eid, "alice.near", Outcome.YES, 100, CLOSE)


def test_take_position_unknown_event():
    m, _ = open_market()
    with pytest.raises(SettlementError, match="UnknownEvent"):
        m.take_position(999, "alice.near", Outcome.YES, 100, 10)


def test_resolve_only_resolver():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    with pytest.raises(SettlementError, match="NotResolver"):
        m.resolve(eid, "mallory.near", Outcome.YES, CLOSE)


def test_resolve_only_after_close():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    with pytest.raises(SettlementError, match="MarketStillOpen"):
        m.resolve(eid, "r.near", Outcome.YES, CLOSE - 1)


def test_resolve_is_once():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    with pytest.raises(SettlementError, match="AlreadyResolved"):
        m.resolve(eid, "r.near", Outcome.NO, CLOSE)


def test_settle_pays_pro_rata_and_conserves():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 75, 10)
    m.take_position(eid, "carol.near", Outcome.YES, 25, 10)
    m.take_position(eid, "bob.near", Outcome.NO, 100, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    a = m.settle(eid, "alice.near")
    c = m.settle(eid, "carol.near")
    assert a == 150
    assert c == 50
    assert a + c == 200
    e = m.get_event(eid)
    assert e["escrow"] == 0
    assert e["phase"] == Phase.SETTLED.value


def test_dust_sweep_last_winner_takes_remainder():
    m, eid = open_market()
    for who in ("w1.near", "w2.near", "w3.near"):
        m.take_position(eid, who, Outcome.YES, 1, 10)
    m.take_position(eid, "loser.near", Outcome.NO, 2, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    p1 = m.settle(eid, "w1.near")
    p2 = m.settle(eid, "w2.near")
    p3 = m.settle(eid, "w3.near")
    assert (p1, p2, p3) == (1, 1, 3)
    assert p1 + p2 + p3 == 5
    assert m.get_event(eid)["escrow"] == 0


def test_settle_is_idempotent_per_account():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    m.settle(eid, "alice.near")
    with pytest.raises(SettlementError, match="AlreadyClaimed"):
        m.settle(eid, "alice.near")


def test_settle_loser_gets_nothing():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    m.take_position(eid, "bob.near", Outcome.NO, 40, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    with pytest.raises(SettlementError, match="NothingToClaim"):
        m.settle(eid, "bob.near")


def test_no_winners_refunds_every_staker():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 60, 10)
    m.take_position(eid, "bob.near", Outcome.YES, 40, 10)
    m.resolve(eid, "r.near", Outcome.NO, CLOSE)
    assert m.settle(eid, "alice.near") == 60
    assert m.settle(eid, "bob.near") == 40
    assert m.get_event(eid)["escrow"] == 0


def test_void_rejected_before_grace():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    with pytest.raises(SettlementError, match="VoidTooEarly"):
        m.void_event(eid, CLOSE + VOID_GRACE_NS - 1)


def test_void_lets_every_staker_withdraw_own_stake():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    m.take_position(eid, "bob.near", Outcome.NO, 40, 10)
    assert m.is_voidable(eid, CLOSE + VOID_GRACE_NS)
    m.void_event(eid, CLOSE + VOID_GRACE_NS)
    assert m.get_event(eid)["phase"] == Phase.VOIDED.value
    assert m.settle(eid, "alice.near") == 100
    assert m.settle(eid, "bob.near") == 40
    assert m.get_event(eid)["escrow"] == 0


def test_resolve_after_void_is_rejected():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    m.void_event(eid, CLOSE + VOID_GRACE_NS)
    with pytest.raises(SettlementError, match="MarketVoided"):
        m.resolve(eid, "r.near", Outcome.YES, CLOSE + VOID_GRACE_NS)


def test_partial_settlement_not_finalized_until_escrow_zero():
    m, eid = open_market()
    m.take_position(eid, "alice.near", Outcome.YES, 60, 10)
    m.take_position(eid, "carol.near", Outcome.YES, 40, 10)
    m.take_position(eid, "bob.near", Outcome.NO, 100, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    m.settle(eid, "alice.near")
    assert m.get_event(eid)["phase"] == Phase.RESOLVED.value
    assert m.get_event(eid)["escrow"] > 0
    m.settle(eid, "carol.near")
    assert m.get_event(eid)["phase"] == Phase.SETTLED.value
    assert m.get_event(eid)["escrow"] == 0


def test_is_voidable_false_for_unknown_and_within_grace():
    m, eid = open_market()
    assert not m.is_voidable(eid, CLOSE + 1)
    assert not m.is_voidable(12345, CLOSE + VOID_GRACE_NS)
