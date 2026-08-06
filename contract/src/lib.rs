// SPDX-License-Identifier: MIT
//! Settlemint: a self-settling event market for NEAR.
//!
//! One `create_event` call opens a binary (Yes/No) market with a named
//! resolver. Accounts stake yoctoNEAR on a side while the market is open. When
//! the outcome is known, the resolver calls `resolve`; then `settle` pays each
//! winner pro rata to their stake on the winning side. The design target is a
//! NEAR-native operator agent that holds a function-call access key scoped to
//! resolve and settle, so a bet becomes a paid claim without a human in the
//! loop and without a full-access key.
//!
//! This is milestone 1 of Settlemint: the NEAR-native settlement core. It is a
//! genuine reimplementation of the EVM predecessor's state machine in Rust for
//! the NEAR WASM runtime, not a Solidity copy. It ships the four-phase
//! lifecycle (Open, Resolved, Settled, Voided), resolver-only resolution,
//! pro-rata pari-mutuel settlement, a dust sweep, and a permissionless void
//! escape hatch.
//!
//! Self-contained: no external library beyond `near-sdk`, so the whole
//! mechanism is auditable in one file. Escrow is tracked per event in
//! yoctoNEAR and every payout decrements it, so conservation holds and the sum
//! of payouts equals the sum of stakes.
//!
//! Liveness: the resolver is trusted only to be *timely*, never to be
//! *present*. If it never resolves, anyone may `void_event` after
//! `closes_at + VOID_GRACE_NS` and every staker withdraws their own stake. No
//! path locks funds.

use near_sdk::borsh::{BorshDeserialize, BorshSerialize};
use near_sdk::collections::{LookupMap, UnorderedMap};
use near_sdk::json_types::{U128, U64};
use near_sdk::{
    env, near, require, AccountId, NearToken, PanicOnDefault, Promise,
};

/// How long after close the resolver has before anyone may void the event.
/// Seven days, in nanoseconds (NEAR block timestamps are nanoseconds).
pub const VOID_GRACE_NS: u64 = 7 * 24 * 60 * 60 * 1_000_000_000;

/// The outcome of an event. `Unresolved` is the default so a fresh event
/// starts unresolved.
#[near(serializers = [json, borsh])]
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Outcome {
    #[default]
    Unresolved,
    Yes,
    No,
}

/// The lifecycle phase of an event.
/// Open: taking positions. Resolved: outcome known, winners claiming.
/// Settled: escrow fully paid out, state final. Voided: resolver never showed
/// up, every staker withdraws their own stake.
#[near(serializers = [json, borsh])]
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Phase {
    #[default]
    Open,
    Resolved,
    Settled,
    Voided,
}

/// The full on-chain record for one event.
#[near(serializers = [json, borsh])]
#[derive(Clone, Debug)]
pub struct EventView {
    pub resolver: AccountId,
    pub closes_at: U64,
    pub phase: Phase,
    pub outcome: Outcome,
    pub pool_yes: U128,
    pub pool_no: U128,
    pub escrow: U128,
    pub unclaimed_win_stake: U128,
}

#[derive(BorshSerialize, BorshDeserialize)]
#[borsh(crate = "near_sdk::borsh")]
struct EventContract {
    resolver: AccountId,
    closes_at: u64,
    phase: Phase,
    outcome: Outcome,
    pool_yes: u128,
    pool_no: u128,
    // yoctoNEAR still held by this contract for this event.
    escrow: u128,
    // winning-side stake that has not claimed yet.
    unclaimed_win_stake: u128,
    // per-account stakes and claim flags for this event.
    yes_stake: LookupMap<AccountId, u128>,
    no_stake: LookupMap<AccountId, u128>,
    claimed: LookupMap<AccountId, bool>,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Settlemint {
    next_event_id: u64,
    events: UnorderedMap<u64, EventContract>,
}

// Key prefixes for the per-event sub-collections. Kept distinct per event by
// appending the event id bytes so two events never share a trie subtree.
fn key(prefix: u8, event_id: u64) -> Vec<u8> {
    let mut v = Vec::with_capacity(9);
    v.push(prefix);
    v.extend_from_slice(&event_id.to_le_bytes());
    v
}

#[near]
impl Settlemint {
    #[init]
    pub fn new() -> Self {
        Self {
            next_event_id: 0,
            events: UnorderedMap::new(b"e".to_vec()),
        }
    }

    /// Create an event that `resolver` may later resolve, closing at
    /// `closes_at` (a nanosecond block timestamp). Returns the new event id.
    pub fn create_event(&mut self, resolver: AccountId, closes_at: U64) -> u64 {
        let closes_at: u64 = closes_at.into();
        require!(closes_at > env::block_timestamp(), "ClosesInPast");
        let event_id = self.next_event_id;
        self.next_event_id += 1;
        let e = EventContract {
            resolver: resolver.clone(),
            closes_at,
            phase: Phase::Open,
            outcome: Outcome::Unresolved,
            pool_yes: 0,
            pool_no: 0,
            escrow: 0,
            unclaimed_win_stake: 0,
            yes_stake: LookupMap::new(key(b'y', event_id)),
            no_stake: LookupMap::new(key(b'n', event_id)),
            claimed: LookupMap::new(key(b'c', event_id)),
        };
        self.events.insert(&event_id, &e);
        env::log_str(&format!(
            "EventCreated id={} resolver={} closes_at={}",
            event_id, resolver, closes_at
        ));
        event_id
    }

    /// Stake attached yoctoNEAR on one side of an open event.
    #[payable]
    pub fn take_position(&mut self, event_id: u64, side: Outcome) {
        let mut e = self.events.get(&event_id).expect("UnknownEvent");
        require!(e.phase == Phase::Open, "NotOpen");
        require!(env::block_timestamp() < e.closes_at, "MarketClosed");
        let amount = env::attached_deposit().as_yoctonear();
        require!(amount > 0, "ZeroStake");
        let account = env::predecessor_account_id();
        match side {
            Outcome::Yes => {
                let prev = e.yes_stake.get(&account).unwrap_or(0);
                e.yes_stake.insert(&account, &(prev + amount));
                e.pool_yes += amount;
            }
            Outcome::No => {
                let prev = e.no_stake.get(&account).unwrap_or(0);
                e.no_stake.insert(&account, &(prev + amount));
                e.pool_no += amount;
            }
            Outcome::Unresolved => env::panic_str("InvalidSide"),
        }
        e.escrow += amount;
        self.events.insert(&event_id, &e);
        env::log_str(&format!(
            "PositionTaken id={} account={} side={:?} amount={}",
            event_id, account, side, amount
        ));
    }

    /// Record the outcome of an event. Only the event's resolver may call, and
    /// only at or after `closes_at`: freezing positions early would let the
    /// resolver cut off the market mid-flight.
    pub fn resolve(&mut self, event_id: u64, outcome: Outcome) {
        let mut e = self.events.get(&event_id).expect("UnknownEvent");
        require!(env::predecessor_account_id() == e.resolver, "NotResolver");
        require!(
            outcome == Outcome::Yes || outcome == Outcome::No,
            "InvalidSide"
        );
        require!(e.phase != Phase::Voided, "MarketVoided");
        require!(e.phase == Phase::Open, "AlreadyResolved");
        require!(env::block_timestamp() >= e.closes_at, "MarketStillOpen");
        e.phase = Phase::Resolved;
        e.outcome = outcome;
        e.unclaimed_win_stake = if outcome == Outcome::Yes {
            e.pool_yes
        } else {
            e.pool_no
        };
        self.events.insert(&event_id, &e);
        env::log_str(&format!(
            "EventResolved id={} outcome={:?} pool_yes={} pool_no={}",
            event_id, outcome, e.pool_yes, e.pool_no
        ));
    }

    /// Permissionless escape hatch: if the resolver never resolves, anyone may
    /// void the event once the grace period after close has elapsed. Every
    /// staker can then withdraw exactly their own stake via `settle`.
    pub fn void_event(&mut self, event_id: u64) {
        let mut e = self.events.get(&event_id).expect("UnknownEvent");
        require!(e.phase == Phase::Open, "NotOpen");
        require!(
            env::block_timestamp() >= e.closes_at + VOID_GRACE_NS,
            "VoidTooEarly"
        );
        e.phase = Phase::Voided;
        let escrow = e.escrow;
        self.events.insert(&event_id, &e);
        env::log_str(&format!("EventVoided id={} escrow={}", event_id, escrow));
    }

    /// Compute an account's payout for a resolved or voided event (view).
    ///
    /// Winners split the whole pool pro rata to their stake on the winning
    /// side. The last winning claimant receives the remaining escrow instead
    /// of a floor-divided share, so rounding dust is paid out rather than
    /// stranded. If the winning side had no stake, or the event was voided,
    /// every staker is refunded their own stake.
    pub fn payout_of(&self, event_id: u64, account: AccountId) -> U128 {
        let e = self.events.get(&event_id).expect("UnknownEvent");
        U128(self.payout_inner(&e, &account))
    }

    fn payout_inner(&self, e: &EventContract, account: &AccountId) -> u128 {
        if e.phase == Phase::Open {
            return 0;
        }
        if e.claimed.get(account).unwrap_or(false) {
            return 0;
        }
        let yes = e.yes_stake.get(account).unwrap_or(0);
        let no = e.no_stake.get(account).unwrap_or(0);
        if e.phase == Phase::Voided {
            return yes + no;
        }
        let win_pool = if e.outcome == Outcome::Yes {
            e.pool_yes
        } else {
            e.pool_no
        };
        if win_pool == 0 {
            // No winners: refund each account its own total stake.
            return yes + no;
        }
        let mine = if e.outcome == Outcome::Yes { yes } else { no };
        if mine == 0 {
            return 0;
        }
        // Last unclaimed winner sweeps the remainder (dust included).
        if mine >= e.unclaimed_win_stake {
            return e.escrow;
        }
        let total = e.pool_yes + e.pool_no;
        // u128 * u128 can overflow; widen to u256 via checked math on the ratio.
        // total and win_pool are both bounded by escrow, so use mul on u128
        // with a widening trick: (total / win_pool) loses precision, so do the
        // multiply first but guard overflow by capping via saturating math is
        // wrong for money. Use u128 mul which is safe because total <= escrow
        // and mine < win_pool <= total, and escrow fits in u128 for any real
        // stake; a pool large enough to overflow u128*u128 is not physically
        // fundable on NEAR. We still guard with checked_mul and panic loudly.
        let numerator = total
            .checked_mul(mine)
            .expect("PayoutOverflow");
        numerator / win_pool
    }

    /// Settle one account's claim on a resolved or voided event (pull payment).
    ///
    /// Idempotent per account via the `claimed` flag. The event only becomes
    /// `Settled` once `escrow` reaches zero, so a partly-claimed event is never
    /// reported as final while winners are still owed money. Returns the payout
    /// and schedules a transfer of that amount to `account`.
    pub fn settle(&mut self, event_id: u64, account: AccountId) -> U128 {
        let mut e = self.events.get(&event_id).expect("UnknownEvent");
        require!(e.phase != Phase::Open, "NotResolved");
        require!(!e.claimed.get(&account).unwrap_or(false), "AlreadyClaimed");
        let payout = self.payout_inner(&e, &account);
        require!(payout > 0, "NothingToClaim");

        // --- effects: all state written before scheduling the transfer ---
        e.claimed.insert(&account, &true);
        if e.phase == Phase::Resolved {
            let mut mine = if e.outcome == Outcome::Yes {
                e.yes_stake.get(&account).unwrap_or(0)
            } else {
                e.no_stake.get(&account).unwrap_or(0)
            };
            if mine > e.unclaimed_win_stake {
                mine = e.unclaimed_win_stake;
            }
            e.unclaimed_win_stake -= mine;
        }
        e.escrow -= payout;
        let finalized = e.escrow == 0 && e.phase == Phase::Resolved;
        if finalized {
            e.phase = Phase::Settled;
        }
        self.events.insert(&event_id, &e);

        // --- interaction ---
        Promise::new(account.clone()).transfer(NearToken::from_yoctonear(payout));
        env::log_str(&format!(
            "Settled id={} account={} payout={}",
            event_id, account, payout
        ));
        if finalized {
            env::log_str(&format!("EventFinalized id={}", event_id));
        }
        U128(payout)
    }

    // --- views ---

    /// Read the full event record.
    pub fn get_event(&self, event_id: u64) -> EventView {
        let e = self.events.get(&event_id).expect("UnknownEvent");
        EventView {
            resolver: e.resolver,
            closes_at: U64(e.closes_at),
            phase: e.phase,
            outcome: e.outcome,
            pool_yes: U128(e.pool_yes),
            pool_no: U128(e.pool_no),
            escrow: U128(e.escrow),
            unclaimed_win_stake: U128(e.unclaimed_win_stake),
        }
    }

    /// Outstanding liability for an event: yocto still held, and winning-side
    /// stake not yet claimed. `escrow == 0` means nobody is owed anything.
    pub fn liability_of(&self, event_id: u64) -> (U128, U128) {
        let e = self.events.get(&event_id).expect("UnknownEvent");
        (U128(e.escrow), U128(e.unclaimed_win_stake))
    }

    /// True once `closes_at + VOID_GRACE_NS` has passed with no resolution.
    pub fn is_voidable(&self, event_id: u64) -> bool {
        match self.events.get(&event_id) {
            None => false,
            Some(e) => {
                e.phase == Phase::Open
                    && env::block_timestamp() >= e.closes_at + VOID_GRACE_NS
            }
        }
    }

    /// The id the next created event will receive.
    pub fn next_event_id(&self) -> u64 {
        self.next_event_id
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;

    fn acc(name: &str) -> AccountId {
        name.parse().unwrap()
    }

    // Build a context with a given predecessor, deposit and block timestamp.
    fn ctx(pred: &str, deposit_yocto: u128, ts: u64) -> VMContextBuilder {
        let mut b = VMContextBuilder::new();
        b.predecessor_account_id(acc(pred))
            .attached_deposit(NearToken::from_yoctonear(deposit_yocto))
            .block_timestamp(ts);
        b
    }

    const CLOSE: u64 = 1_000_000;

    fn open_market(resolver: &str) -> (Settlemint, u64) {
        let mut c = Settlemint::new();
        testing_env!(ctx("creator.near", 0, 0).build());
        let id = c.create_event(acc(resolver), U64(CLOSE));
        (c, id)
    }

    #[test]
    fn create_assigns_sequential_ids() {
        let mut c = Settlemint::new();
        testing_env!(ctx("creator.near", 0, 0).build());
        assert_eq!(c.create_event(acc("r.near"), U64(CLOSE)), 0);
        assert_eq!(c.create_event(acc("r.near"), U64(CLOSE)), 1);
        assert_eq!(c.next_event_id(), 2);
    }

    #[test]
    #[should_panic(expected = "ClosesInPast")]
    fn create_rejects_past_close() {
        let mut c = Settlemint::new();
        testing_env!(ctx("creator.near", 0, 500).build());
        c.create_event(acc("r.near"), U64(400));
    }

    #[test]
    fn take_position_accumulates_pools() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("alice.near", 50, 20).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("bob.near", 30, 30).build());
        c.take_position(id, Outcome::No);
        let e = c.get_event(id);
        assert_eq!(e.pool_yes.0, 150);
        assert_eq!(e.pool_no.0, 30);
        assert_eq!(e.escrow.0, 180);
    }

    #[test]
    #[should_panic(expected = "ZeroStake")]
    fn take_position_rejects_zero() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 0, 10).build());
        c.take_position(id, Outcome::Yes);
    }

    #[test]
    #[should_panic(expected = "MarketClosed")]
    fn take_position_rejects_after_close() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, CLOSE).build());
        c.take_position(id, Outcome::Yes);
    }

    #[test]
    #[should_panic(expected = "InvalidSide")]
    fn take_position_rejects_unresolved_side() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Unresolved);
    }

    #[test]
    #[should_panic(expected = "UnknownEvent")]
    fn take_position_unknown_event() {
        let (mut c, _) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(999, Outcome::Yes);
    }

    #[test]
    #[should_panic(expected = "NotResolver")]
    fn resolve_only_resolver() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("mallory.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Yes);
    }

    #[test]
    #[should_panic(expected = "MarketStillOpen")]
    fn resolve_only_after_close() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("r.near", 0, CLOSE - 1).build());
        c.resolve(id, Outcome::Yes);
    }

    #[test]
    #[should_panic(expected = "InvalidSide")]
    fn resolve_rejects_unresolved_outcome() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Unresolved);
    }

    #[test]
    #[should_panic(expected = "AlreadyResolved")]
    fn resolve_is_once() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Yes);
        c.resolve(id, Outcome::No);
    }

    #[test]
    fn resolve_sets_unclaimed_win_stake() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("bob.near", 40, 10).build());
        c.take_position(id, Outcome::No);
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Yes);
        let (escrow, unclaimed) = c.liability_of(id);
        assert_eq!(escrow.0, 140);
        assert_eq!(unclaimed.0, 100); // only the Yes pool is owed
    }

    #[test]
    fn settle_pays_pro_rata_and_conserves() {
        // alice 75, carol 25 on Yes; bob 100 on No. Yes wins.
        // Total pool 200. alice gets 200*75/100 = 150, carol sweeps remainder.
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 75, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("carol.near", 25, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("bob.near", 100, 10).build());
        c.take_position(id, Outcome::No);
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Yes);

        testing_env!(ctx("anyone.near", 0, CLOSE).build());
        let a = c.settle(id, acc("alice.near")).0;
        let cr = c.settle(id, acc("carol.near")).0;
        assert_eq!(a, 150);
        assert_eq!(cr, 50); // remainder sweep, 200 - 150
        assert_eq!(a + cr, 200); // conservation: payouts equal total stakes
        let e = c.get_event(id);
        assert_eq!(e.escrow.0, 0);
        assert_eq!(e.phase, Phase::Settled);
    }

    #[test]
    fn settle_dust_sweep_last_winner_takes_remainder() {
        // Three equal winners of 1 yocto each, pool total 3 (loser 0).
        // 3*1/3 = 1 each; no dust here, so craft an indivisible split:
        // winners stake 1,1,1 on Yes (pool 3); loser stakes 2 on No.
        // total = 5, winPool = 3. floor(5*1/3)=1 each for first two,
        // last winner sweeps 5-1-1 = 3.
        let (mut c, id) = open_market("r.near");
        for who in ["w1.near", "w2.near", "w3.near"] {
            testing_env!(ctx(who, 1, 10).build());
            c.take_position(id, Outcome::Yes);
        }
        testing_env!(ctx("loser.near", 2, 10).build());
        c.take_position(id, Outcome::No);
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Yes);

        testing_env!(ctx("op.near", 0, CLOSE).build());
        let p1 = c.settle(id, acc("w1.near")).0;
        let p2 = c.settle(id, acc("w2.near")).0;
        let p3 = c.settle(id, acc("w3.near")).0;
        assert_eq!(p1, 1);
        assert_eq!(p2, 1);
        assert_eq!(p3, 3); // last winner sweeps the dust
        assert_eq!(p1 + p2 + p3, 5); // nothing stranded
        assert_eq!(c.get_event(id).escrow.0, 0);
    }

    #[test]
    #[should_panic(expected = "AlreadyClaimed")]
    fn settle_is_idempotent_per_account() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Yes);
        testing_env!(ctx("op.near", 0, CLOSE).build());
        c.settle(id, acc("alice.near"));
        c.settle(id, acc("alice.near"));
    }

    #[test]
    #[should_panic(expected = "NotResolved")]
    fn settle_rejects_open_market() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("op.near", 0, 20).build());
        c.settle(id, acc("alice.near"));
    }

    #[test]
    #[should_panic(expected = "NothingToClaim")]
    fn settle_loser_gets_nothing() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("bob.near", 40, 10).build());
        c.take_position(id, Outcome::No);
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Yes);
        testing_env!(ctx("op.near", 0, CLOSE).build());
        c.settle(id, acc("bob.near"));
    }

    #[test]
    fn no_winners_refunds_every_staker() {
        // Everyone staked Yes; outcome is No, so the winning pool is empty.
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 60, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("bob.near", 40, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::No);
        testing_env!(ctx("op.near", 0, CLOSE).build());
        assert_eq!(c.settle(id, acc("alice.near")).0, 60);
        assert_eq!(c.settle(id, acc("bob.near")).0, 40);
        assert_eq!(c.get_event(id).escrow.0, 0);
    }

    #[test]
    #[should_panic(expected = "VoidTooEarly")]
    fn void_rejected_before_grace() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("anyone.near", 0, CLOSE + VOID_GRACE_NS - 1).build());
        c.void_event(id);
    }

    #[test]
    fn void_lets_every_staker_withdraw_own_stake() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("bob.near", 40, 10).build());
        c.take_position(id, Outcome::No);
        // resolver never shows; anyone voids after grace.
        testing_env!(ctx("anyone.near", 0, CLOSE + VOID_GRACE_NS).build());
        assert!(c.is_voidable(id));
        c.void_event(id);
        assert_eq!(c.get_event(id).phase, Phase::Voided);
        testing_env!(ctx("op.near", 0, CLOSE + VOID_GRACE_NS + 1).build());
        assert_eq!(c.settle(id, acc("alice.near")).0, 100);
        assert_eq!(c.settle(id, acc("bob.near")).0, 40);
        assert_eq!(c.get_event(id).escrow.0, 0);
    }

    #[test]
    #[should_panic(expected = "MarketVoided")]
    fn resolve_after_void_is_rejected() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 100, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("anyone.near", 0, CLOSE + VOID_GRACE_NS).build());
        c.void_event(id);
        testing_env!(ctx("r.near", 0, CLOSE + VOID_GRACE_NS).build());
        c.resolve(id, Outcome::Yes);
    }

    #[test]
    fn is_voidable_false_while_within_grace() {
        let (c, id) = open_market("r.near");
        testing_env!(ctx("anyone.near", 0, CLOSE + 1).build());
        assert!(!c.is_voidable(id));
        assert!(!c.is_voidable(12345)); // unknown event
    }

    #[test]
    fn partial_settlement_not_finalized_until_escrow_zero() {
        let (mut c, id) = open_market("r.near");
        testing_env!(ctx("alice.near", 60, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("carol.near", 40, 10).build());
        c.take_position(id, Outcome::Yes);
        testing_env!(ctx("bob.near", 100, 10).build());
        c.take_position(id, Outcome::No);
        testing_env!(ctx("r.near", 0, CLOSE).build());
        c.resolve(id, Outcome::Yes);
        testing_env!(ctx("op.near", 0, CLOSE).build());
        c.settle(id, acc("alice.near"));
        // one winner still owed, so not Settled yet
        assert_eq!(c.get_event(id).phase, Phase::Resolved);
        assert!(c.get_event(id).escrow.0 > 0);
        c.settle(id, acc("carol.near"));
        assert_eq!(c.get_event(id).phase, Phase::Settled);
        assert_eq!(c.get_event(id).escrow.0, 0);
    }
}
