# Settlemint, a two-minute demo

A settlement core for NEAR that pays every winner and lands escrow at exactly
zero. This is milestone 1: the NEAR-native Rust contract, tested and building to
a deployable WASM, with a Python mirror kept in cross-language parity and a
replayable UI.

## 0:00 The problem (spoken)

"When an on-chain market resolves a real-world question, someone decides the
outcome and someone pays every winner. If a resolver key goes silent, escrow can
be stranded. If floor division drops a yocto, someone is short-changed. Settlemint
makes settlement mechanical and provably complete on NEAR."

## 0:20 The core is real

```bash
cd contract && cargo test
```

Point at the result: **23 tests pass**. Name three: pro-rata payout conserves to
the total, the last winner sweeps the dust so escrow hits zero, and a silent
resolver cannot lock funds because anyone can void after the grace window.

```bash
cargo build --release --target wasm32-unknown-unknown
ls -la target/wasm32-unknown-unknown/release/settlemint.wasm
```

"That 205 KB WASM is exactly what a NEAR testnet deploy uploads. It compiles for
the NEAR runtime, not just for host tests."

## 0:50 The math is the same off-chain and on-chain

```bash
cd .. && PYTHONPATH=. python -m pytest tests -q
```

**32 tests pass.** Open `tests/test_parity.py`: "these literals, 150 and 50 for a
pro-rata split, 1/1/3 for the dust sweep, are the exact values the Rust tests
assert. If either implementation drifts by a yocto, a test fails. The operator's
off-chain view can never disagree with the chain."

## 1:20 Watch it settle

```bash
open ui/index.html
```

Press **Run settlement**. The market opens, three stakes land on opposite sides,
the resolver records Yes after close, and the two winners are paid. Watch the
escrow-conservation meter: the amber segment is the dust the last winner sweeps,
and the escrow counter drains to **0**. "Payouts equal stakes to the last yocto.
Nothing stranded."

## 1:50 The honest line

"Testnet only. No mainnet, no public receipt yet, no users, no audit. Everything
not built is written down in `docs/LIMITATIONS.md`. What is built is the
settlement core, tested to 55 checks with cross-language parity, and it compiles
to a deployable NEAR contract today."
