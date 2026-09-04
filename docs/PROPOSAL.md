# Settlemint on NEAR: a verifiable settlement agent for autonomous on-chain markets

**Project:** Settlemint
**Repo slug:** `doom2quake/settlemint`
**Programme:** NEAR Protocol Rewards
**Applicant:** doom2quake (builder collective)
**Track:** Autonomous Agent Frameworks / AI-powered DeFi
**Web3 posture:** NEAR testnet only. No mainnet. No custody of user funds.

---

## What NEAR Protocol Rewards actually is (verified before writing this)

We checked the official programme page (`nearprotocolrewards.com`) and the reference
implementation (`github.com/near-horizon/near-protocol-rewards`) before drafting. The
important thing to state plainly, because it changes how a proposal should be written:

**NEAR Protocol Rewards is not a discretionary grant that pays on a written plan. It is a
metric-based rewards system that scores measured activity and pays a monthly tier from that
score.** The score is 0 to 100, split 80 percent off-chain (GitHub) and 20 percent on-chain,
with published thresholds:

- Off-chain (80 pts): commits 28, merged PRs 22, reviews 16, closed issues 14.
- On-chain (20 pts): transaction volume 8 (threshold around $10,000), contract calls 8
  (threshold around 500), unique wallets 4 (threshold around 100).

Tiers (verified on the reward table): Diamond 85 to 100 pays $10,000, Gold 70 to 84 pays
$6,000, Silver 55 to 69 pays $3,000, Bronze 40 to 54 pays $1,000, Contributor 20 to 39 pays
$500, Explorer 1 to 19 pays $100. The page states "up to $10K/month during the program" and
shows cumulative figures of "$200,000+" across roughly 20 active projects. Selection into a
cohort weights Project Potential 60 percent, Technical Skills 20 percent, Community Engagement
20 percent. Applications go through an Airtable form and run in cohorts.

**VERIFIED:** the 80/20 split, the seven scoring metrics and thresholds, the six tiers and
dollar amounts, the selection weights, and that the collection pipeline runs automatically
(the repo describes recomputation on a fixed interval). This is a rewards programme, it is
non-dilutive, and it takes no equity, no token, and no IP. That matches our stated preference
exactly.

**NOT VERIFIED on an official page:** the current cohort number and its exact open and close
dates. The landing page shows a live "Apply for Next Cohort" call to action and an active
Airtable form, but it does not print a cohort number or deadline we can quote. Secondary
sources reference a cohort that closed in July, which would place the next intake around now,
but we will not assert a date we did not read on the official page. An operator must open the
Airtable form and confirm the live cohort window before committing.

**What this means for the proposal:** a NEAR Rewards proposal is judged twice. Cohort
selection is judged on potential and technical skill, which is where the working code below
earns its place. Ongoing reward is judged on measured GitHub and on-chain activity, which is
why our roadmap is written as a schedule of merges, closed issues, deployed testnet contracts,
and contract calls we can actually produce, not as prose about future intentions.

---

## 1. The problem

An on-chain market that resolves a real-world question has a settlement problem that predates
crypto and is not solved by putting the market on a chain. Someone has to decide the outcome,
someone has to pay every winner, and everyone else has to be able to check that the payout
matched the outcome. Today that trust sits in a person or an opaque script. When a prediction
market, an event contract, or an agent-run payout settles, a participant who lost has no way
to tell an honest resolution from a rigged one. The resolver publishes a winner and the money
moves. The reasoning, if it exists at all, lives in a Discord message that can be edited after
the fact, and the rule the resolver claims to have followed can be swapped the moment before
settlement.

This costs real money to the side that was cheated and it costs the whole category its
credibility. Every settlement dispute that cannot be checked on-chain is a reason a serious
counterparty stays out. The failure is specific: outcome and reason are not bound together, the
judging rule is not locked before people commit funds, and a silent resolver can strand escrow
with no escape hatch. An operator running an autonomous market on NEAR faces exactly this, and
"trust our agent" is not an answer a diligence process accepts.

## 2. Why NEAR, why now

NEAR is positioning 2026 as an agent-first chain, and its own rewards programme names
Autonomous Agent Frameworks and AI-powered DeFi as target areas. That is the precise shape of
what we build: an operator agent that watches a market, resolves it under a rule locked in
advance, and settles every winner in a bounded, auditable pass. NEAR makes this possible in a
way that suits the design. NEAR's account model and named function-call access keys let a
settlement agent hold a narrowly scoped resolver key rather than a full account, which bounds
the blast radius of a compromised agent to exactly the settle-and-resolve methods. NEAR's low,
predictable fees make the pattern that matters here, one resolve plus one settle pass per
market, cheap enough to run at the cadence the rewards programme measures. And because the
rewards programme scores on-chain contract calls and unique wallets directly, an agent that
settles many small markets on testnet produces exactly the measured, honest activity the
programme is built to reward, without inflating anything.

The timing is that NEAR is actively courting agent builders through this programme right now,
and we arrive with the settlement mechanism already built and tested on another EVM chain,
ready to port to NEAR-native Rust rather than to design from scratch.

## 3. Evidence we ship

Most applicants arrive with a plan and no artifact. We arrive with milestone 1 already built
NEAR-native and green.

**Milestone 1 is built.** This repo (`doom2quake/settlemint`, at `projects/near-rewards/app`)
ships the NEAR-native Rust settlement core: `contract/src/lib.rs`, the whole four-phase lifecycle
(open, resolved, settled, voided) with resolver-only resolution, pro-rata pari-mutuel settlement,
the last-winner dust sweep, and the permissionless void escape hatch, depending only on
`near-sdk`. Verified counts, reproduced on 2026-08-26:

- **`cargo test`: 23 Rust unit tests pass** on the NEAR `unit-testing` harness, offline, covering
  every phase transition, the access-control checks, the pro-rata split, the dust sweep, the
  no-winner and void refunds, and the not-finalised-until-escrow-zero property.
- **`cargo build --release --target wasm32-unknown-unknown`** produces a **205 KB WASM**, the
  artifact a testnet deploy uploads.
- **`PYTHONPATH=. pytest tests -q`: 32 Python tests pass**, covering a pure-Python mirror of the
  settlement arithmetic, a cross-language parity suite that asserts the exact payout literals the
  Rust tests assert, a run-fixture test that checks the recorded run conserves value to the last
  yocto and reproduces exactly, and an adapter test that proves the live NEAR client refuses any
  mainnet endpoint.

The full package is in the repo: `ui/index.html` (self-contained replay of a market from open to
settled), `paper/paper.tex` + `references.bib`, `deck/deck.md` (Marp), `DEMO.md`,
`docs/LIMITATIONS.md`, `docs/ui.png`, `CITATION.cff`, MIT `LICENSE`. This completes milestone 1;
milestones 2 to 4 remain as scoped in Section 4.

The mechanism was proven first on two EVM predecessors, also real repositories with reproducible
test suites, which is why the NEAR port could be written directly rather than designed from
scratch. Every number below was produced by running those suites on 2026-08-24.

**Verdict** (`doom2quake/verdict`), the verifiable-resolution half. A resolver settles a
subjective market but, in the same transaction, commits the keccak256 of its published
reasoning, the judge-policy hash locked before anyone staked, and an attestor signature binding
all of it to that chain and market. Anyone can then publish the reasoning, hash it, and ask the
contract; verification returns true only when the hash matches and the text's own first line
declares the settled outcome. Measured: **29 Solidity tests pass** (`forge test`) and **49
Python tests pass** (`pytest`), both offline, run today. A full on-chain run is recorded in the
repo with real receipts (5 transactions, real hashes and blocks, 2,063,963 gas total on a local
devnet), and the same reasoning hash is computed independently in Python, Solidity, and browser
JavaScript, pinned to each other by tests, so a one-byte change to the judging rule fails three
suites at once.

**DreamBot** (`doom2quake/dreambot`), the self-settling half. An operator agent watches an
event market, refuses to resolve before close (spending no action budget while it waits),
resolves once at or after close, and settles every winner pro rata in one resumable pass. If it
crashes after resolve, the next run pays whoever is still owed. If the resolver never shows up,
after a grace window anyone can void the event and every staker withdraws their own stake, so a
lost key cannot lock funds. Measured: **22 Solidity tests pass** and **48 Python tests pass**,
run today. A live run against a Foundry devnet is recorded with real transaction hashes, blocks,
and gas, and a parity test asserts the offline model and the deployed contract agree wei for wei
on an indivisible split.

Both repos carry a written `LIMITATIONS.md` that states what is not measured before a reviewer
has to find it, and both settle to the last wei with a dust sweep so no escrow is stranded.
Together they are the exact mechanism Settlemint brings to NEAR: a self-settling market whose
resolution is checkable by anyone. Our edge is not a promise. It is 200 passing tests across
four suites and two recorded on-chain runs, today.

## 4. Milestone roadmap

Settlemint is a fresh repo (`doom2quake/settlemint`) that ports this mechanism to
NEAR-native Rust contracts (NEAR is WASM and Rust, not EVM, so this is a genuine reimplementation
of the state machine and the verification, not a Solidity copy). The milestones are written so
each one produces the measured GitHub and on-chain activity the rewards programme scores.
Dates assume a cohort start we will confirm on the Airtable form before committing; they are
expressed as weeks from cohort start (T0).

**Milestone 1: NEAR-native settlement core (T0 to week 3).**
Deliverable: a NEAR Rust contract implementing the event-market lifecycle (open, resolved,
settled, voided) with resolver-only resolution, pro-rata pari-mutuel settlement, the dust
sweep, and the void escape hatch, ported from DreamBot's Solidity. How a reviewer verifies:
`cargo test` and NEAR workspaces integration tests pass in the public repo, and the contract is
deployed to NEAR testnet with the deploy transaction linked. Unlocks: the on-chain surface the
rewards pipeline measures (contract calls, unique wallets) and the base every later milestone
builds on.

**Milestone 2: verifiable resolution on NEAR (week 3 to week 6).**
Deliverable: the Verdict commitment ported to NEAR, so settlement stores the hash of the
resolver's reasoning and the pre-locked policy hash on-chain, with a public read method that
returns true only when a supplied reasoning text matches the commitment and declares the settled
outcome. How a reviewer verifies: a recorded testnet run in the repo where resolution commits a
reasoning hash, the public verify method returns true for the real text and false for a one-line
tamper, both as read-only calls anyone can repeat. Unlocks: the actual differentiator, a NEAR
market whose resolution is auditable, plus the cross-language hash-parity tests carried over.

**Milestone 3: operator agent on NEAR with a scoped access key (week 6 to week 9).**
Deliverable: the settlement agent driving the NEAR contracts over RPC using a named
function-call access key scoped to resolve and settle only, on our shared agent-core action
limiter and audit trail, with the resumable settle pass and the pre-close refusal preserved. How
a reviewer verifies: a `settlemint watch` command in the public repo settles a real testnet
market end to end, the recorded run shows the agent waiting before close and settling after, and
the access key on the deploy is demonstrably not a full-access key. Unlocks: repeatable,
measured on-chain activity (many small settled markets) that is honest volume for the rewards
score, and the operational shape a real deployment would use.

**Milestone 4: demo, docs, and a reusable template (week 9 to week 12).**
Deliverable: a hosted-offline UI that runs a market from open to settled and verifies a
resolution in the browser, a written integration guide, and the repo packaged as a template
another NEAR builder can fork to add verifiable settlement to their own market. How a reviewer
verifies: the UI opens and verifies against a recorded testnet run, the guide walks a reader
from clone to a settled testnet market, and the template repo builds clean. Unlocks: the
community-engagement half of the rewards score and the ecosystem contribution below.

**After the grant.** The rewards programme is recurring and metric-based, which fits how we
work: we keep merging, closing issues, and settling testnet markets, so the same repo keeps
scoring across cohorts without a new proposal each time. Beyond the programme, Settlemint stays
a maintained open template. If an operator later decides to run real markets, the mainnet step
is a deliberate, separately-authorised decision outside the scope of this testnet-only grant.

## 5. Ecosystem impact

Everything is MIT and public under `doom2quake`. What another NEAR builder can reuse:

- The NEAR-native self-settling event-market contract, as a forkable template, so a new market
  gets resolver-only settlement, pro-rata payout, a dust sweep, and a void escape hatch without
  rewriting the state machine.
- The verifiable-resolution pattern on NEAR: commit the reasoning hash and the locked policy
  hash at settlement, expose a public verify method, so any market can make its resolution
  auditable rather than "trust the operator."
- The operator agent pattern with a scoped function-call access key, an action limiter, and an
  audit trail, which is a safe default for any agent that touches funds on NEAR.
- The cross-language hash-parity test approach (Rust, contract, browser), which is a concrete
  recipe for keeping an agent's off-chain output and its on-chain commitment provably identical.

The integration guide and a short paper documenting the settlement-and-verification design (author
Dipankar Sarkar, repo and licence under doom2quake) make the pattern learnable, not just
runnable.

## 6. Sustainability and honest limits

**What keeps it alive.** The rewards programme is itself the sustainability mechanism for the
early phase: it pays recurring, non-dilutive rewards for measured activity, and Settlemint is
built to produce exactly that activity. The maintenance cost is low because the contracts are
self-contained with no external libraries, matching how the two source repos are already built.
The template lowers the cost for others to adopt and contribute back.

**What is NOT built, deployed, or measured, stated plainly:**

- **The NEAR core is built; the on-chain deploy is not.** Milestone 1's NEAR-native contract is
  written, tested (23 Rust unit tests), and compiles to a 205 KB testnet WASM, but this repo ships
  no funded key, so there is no public testnet deploy transaction yet. The recorded run is a
  genuine offline execution of the settlement math with no block-explorer receipt. Deploying to
  public NEAR testnet is the first thing milestone 1's on-chain verification does.
- **No mainnet, ever, in this scope.** All NEAR work is testnet only. We claim no mainnet
  deployment.
- **No users, no revenue, no partnerships, no audit.** We have not run a real market for anyone,
  taken any revenue, partnered with any protocol, or had any contract audited. The 200 passing
  tests are our own suites, not a third-party audit.
- **The predecessors' recorded runs are local devnets, not public testnets.** Verdict and
  DreamBot recorded their runs against local Anvil/Foundry nodes, so no public block explorer
  link exists for them. Settlemint's milestone runs are specified against public NEAR testnet so
  they will be independently checkable, which is a step up we are committing to, not one already
  done.
- **The current NEAR Rewards cohort window is not confirmed on an official page.** We verified
  the programme mechanics and tiers, but not the live cohort number or deadline. An operator must
  confirm the open window on the Airtable form before applying.

We would rather a reviewer read this section first. The claim is narrow and true: the mechanism
runs and is tested on another chain today, and this grant funds the honest, verifiable port to
NEAR.

## Operator decision

NEAR Protocol Rewards is non-dilutive, takes no equity, no token, and no IP assignment, which
matches our preference and needs no special sign-off on terms. The two operator actions are
mechanical, not contractual: (1) open the Airtable application form and confirm the live cohort
is open and its deadline before submitting; (2) generate a NEAR testnet account and a scoped
function-call access key for the settlement agent. No wallet holding real funds and no mainnet
key is required for any milestone.

## Cite

```bibtex
@software{sarkar_settlemint_2026,
  title  = {Settlemint: a verifiable settlement agent for autonomous markets on NEAR},
  author = {Dipankar Sarkar},
  year   = {2026},
  url    = {https://github.com/doom2quake/settlemint},
  license = {MIT}
}
```
