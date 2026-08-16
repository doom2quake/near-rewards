"""Cross-language parity between the Python model and the NEAR Rust contract.

The Rust unit tests in contract/src/lib.rs assert specific payout literals for
each scenario. This file runs the identical scenarios through the Python model
and asserts the same literals, so the off-chain settlement math and the on-chain
settlement math cannot drift without a test failing on one side or the other.

Each `RUST_*` constant below is the value asserted in the correspondingly named
Rust test. If you change one, the other must change too, on purpose.
"""

from settlemint.model import EventMarket, Outcome, Phase

CLOSE = 1_000_000


def _market():
    m = EventMarket()
    return m, m.create_event("r.near", CLOSE, 0)


# --- settle_pays_pro_rata_and_conserves (Rust asserts a=150, cr=50) ---
RUST_PRO_RATA = {"alice": 150, "carol": 50, "total": 200}


def test_parity_pro_rata():
    m, eid = _market()
    m.take_position(eid, "alice.near", Outcome.YES, 75, 10)
    m.take_position(eid, "carol.near", Outcome.YES, 25, 10)
    m.take_position(eid, "bob.near", Outcome.NO, 100, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    a = m.settle(eid, "alice.near")
    c = m.settle(eid, "carol.near")
    assert a == RUST_PRO_RATA["alice"]
    assert c == RUST_PRO_RATA["carol"]
    assert a + c == RUST_PRO_RATA["total"]
    assert m.get_event(eid)["phase"] == Phase.SETTLED.value


# --- settle_dust_sweep_last_winner_takes_remainder (Rust asserts 1,1,3) ---
RUST_DUST = (1, 1, 3)


def test_parity_dust_sweep():
    m, eid = _market()
    for who in ("w1.near", "w2.near", "w3.near"):
        m.take_position(eid, who, Outcome.YES, 1, 10)
    m.take_position(eid, "loser.near", Outcome.NO, 2, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    got = (
        m.settle(eid, "w1.near"),
        m.settle(eid, "w2.near"),
        m.settle(eid, "w3.near"),
    )
    assert got == RUST_DUST
    assert sum(got) == 5  # nothing stranded


# --- resolve_sets_unclaimed_win_stake (Rust asserts escrow=140, unclaimed=100) ---
RUST_LIABILITY = (140, 100)


def test_parity_liability_after_resolve():
    m, eid = _market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    m.take_position(eid, "bob.near", Outcome.NO, 40, 10)
    m.resolve(eid, "r.near", Outcome.YES, CLOSE)
    assert m.liability_of(eid) == RUST_LIABILITY


# --- no_winners_refunds_every_staker (Rust asserts 60 and 40) ---
RUST_REFUND = {"alice": 60, "bob": 40}


def test_parity_no_winners_refund():
    m, eid = _market()
    m.take_position(eid, "alice.near", Outcome.YES, 60, 10)
    m.take_position(eid, "bob.near", Outcome.YES, 40, 10)
    m.resolve(eid, "r.near", Outcome.NO, CLOSE)
    assert m.settle(eid, "alice.near") == RUST_REFUND["alice"]
    assert m.settle(eid, "bob.near") == RUST_REFUND["bob"]


# --- void_lets_every_staker_withdraw_own_stake (Rust asserts 100 and 40) ---
RUST_VOID_REFUND = {"alice": 100, "bob": 40}


def test_parity_void_refund():
    from settlemint.model import VOID_GRACE_NS

    m, eid = _market()
    m.take_position(eid, "alice.near", Outcome.YES, 100, 10)
    m.take_position(eid, "bob.near", Outcome.NO, 40, 10)
    m.void_event(eid, CLOSE + VOID_GRACE_NS)
    assert m.settle(eid, "alice.near") == RUST_VOID_REFUND["alice"]
    assert m.settle(eid, "bob.near") == RUST_VOID_REFUND["bob"]
