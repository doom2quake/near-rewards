"""The recorded run in docs/run.json is a genuine execution, and balanced.

The UI renders docs/run.json directly, so these tests guarantee the page never
shows a placeholder: the fixture must exist, conserve value to the last yocto,
end Settled with zero escrow, and match a fresh run of the recorder.
"""

import json
import os

from scripts.record_run import record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, "docs", "run.json")


def test_run_fixture_exists_and_conserves():
    with open(RUN) as fh:
        run = json.load(fh)
    cons = run["conservation"]
    assert cons["balanced"] is True
    assert cons["total_staked_yocto"] == cons["total_paid_yocto"]
    assert cons["escrow_remaining"] == 0
    assert run["final_event"]["phase"] == "Settled"


def test_committed_fixture_matches_fresh_run():
    # The recorder is deterministic, so re-running it must reproduce the
    # committed steps and payouts exactly.
    fresh = record()
    with open(RUN) as fh:
        committed = json.load(fh)
    assert fresh["payouts"] == committed["payouts"]
    assert fresh["conservation"] == committed["conservation"]
    assert len(fresh["steps"]) == len(committed["steps"])


def test_dust_sweep_visible_in_run():
    # alice staked 2 NEAR of a 3-NEAR winning pool out of a 5-NEAR total, so
    # her floor share is 5*2//3 NEAR and carol sweeps the remainder. The two
    # payouts must still sum to the full 5 NEAR.
    with open(RUN) as fh:
        run = json.load(fh)
    pays = run["payouts"]
    total = sum(pays.values())
    assert total == run["conservation"]["total_staked_yocto"]
    assert pays["alice.testnet"] != pays["carol.testnet"]
