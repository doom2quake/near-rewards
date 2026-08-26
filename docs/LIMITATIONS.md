# What Settlemint proves, and what it does not

Written so a reviewer does not have to find the gaps by reading source.
Everything below is checkable in this repo.

## What is real and measured

- **The NEAR settlement core.** `contract/src/lib.rs` is the whole milestone-1
  mechanism in one file, with no dependency beyond `near-sdk`: the four-phase
  lifecycle (Open, Resolved, Settled, Voided), resolver-only resolution,
  pro-rata pari-mutuel settlement, a last-winner dust sweep, and a
  permissionless void escape hatch. `cargo test` runs **23 unit tests** against
  it on the NEAR `unit-testing` harness, offline.
- **A deployable artifact.** `cargo build --release --target
  wasm32-unknown-unknown` produces a **205 KB** WASM contract. That is the
  artifact a testnet deploy would upload. Building it is proof the contract
  compiles for the NEAR runtime, not just for host tests.
- **A cross-language mirror, pinned.** `settlemint/model.py` reimplements the
  same settlement arithmetic in Python. `tests/test_parity.py` asserts the exact
  payout literals the Rust unit tests assert (150/50 pro-rata, 1/1/3 dust sweep,
  140/100 liability, and the refund and void cases), so the on-chain and
  off-chain math cannot drift without failing a test on one side. **32 Python
  tests pass.**
- **A recorded run, and the UI renders it.** `scripts/record_run.py` drives a
  full market lifecycle through the offline client and writes `docs/run.json`.
  `tests/test_run_fixture.py` asserts the committed run conserves value to the
  last yocto, ends Settled with zero escrow, and reproduces exactly on a fresh
  run. `ui/index.html` renders that same data, so nothing on the page is a typed
  placeholder.
- **The adapter seam is testnet-only by construction.**
  `tests/test_near_adapter.py` proves `LiveNearClient` refuses a mainnet RPC URL
  and any non-testnet host, and that `build_client()` falls back to the keyless
  offline backend when no credentials are set.

## The recorded run is an offline fixture, not a public testnet receipt

`docs/run.json` is produced by the offline NEAR client, which runs the same
arithmetic as the contract but does not touch a network. It is a genuine
execution of the settlement math, but there is **no public block explorer link**
for it, because no funded testnet key is shipped in this repo. The live backend
(`settlemint/near.py`) targets NEAR testnet given `NEAR_RPC_URL` and a signer;
producing a public-testnet run with a real deploy transaction is the explicit
next step, committed for milestone 1's on-chain verification, not something
already done here.

## What is NOT built, deployed, or measured

- **No mainnet, ever, in this scope.** All NEAR work is testnet only. The live
  client rejects mainnet endpoints in code.
- **No public testnet deploy transaction yet.** The WASM builds; this repo does
  not ship a funded key, so it records the run offline and does not claim a
  deploy receipt it cannot show.
- **Milestones 2 to 4 are not in this repo.** The verifiable-resolution hash
  commitment (milestone 2), the operator agent driving NEAR over a scoped access
  key on vendored `agent_core` (milestone 3), and the forkable template
  (milestone 4) are scoped out. `agent_core` is vendored ready for milestone 3
  but the milestone-1 core does not depend on it.
- **No users, no revenue, no partnerships, no audit.** The 55 passing tests
  across the two suites are our own, not a third-party audit. No real market has
  been run for anyone.
- **The NEAR Rewards cohort window is not confirmed on an official page.** The
  programme mechanics and tiers were verified; the live cohort number and
  deadline were not. An operator must confirm the open window on the Airtable
  form before applying.

We would rather a reviewer read this section first. The claim is narrow and true:
the NEAR settlement core is written, compiles to a testnet WASM, and is tested to
55 passing checks with cross-language parity, today.
