from __future__ import annotations

import sqlite3

from cbcr_platform.contracts import RunRequest


def drain(service):
    while service.process_one():
        pass


def test_selected_functions_are_independent_and_async(services):
    db, _, runs = services
    request = RunRequest(source_id="fixture_alpha", functions=["analyze_profit_presence_mismatch", "analyze_etr_outlier"],
        purpose="risk_assessment", parameters={"analyze_profit_presence_mismatch": {"minimum_profit_margin": 0.2, "maximum_employees": 2}})
    run_id = runs.create(request, "demo")
    assert runs.get(run_id)["status"] == "queued"
    assert len(runs.get(run_id)["function_runs"]) == 2
    assert runs.process_one()
    mid = runs.get(run_id)
    assert sorted(child["status"] for child in mid["function_runs"]) == ["queued", "succeeded"]
    drain(runs)
    completed = runs.get(run_id)
    assert completed["status"] == "completed"
    assert {f["function_code"] for f in runs.findings(run_id)} == {
        "analyze_etr_outlier", "analyze_profit_presence_mismatch"
    }
    assert db.one("SELECT COUNT(*) AS n FROM raw_snapshots WHERE run_id=?", (run_id,))["n"] == 1


def test_failure_is_isolated_to_one_function_run(services, monkeypatch):
    db, _, runs = services
    run_id = runs.create(RunRequest(source_id="fixture_alpha", functions=["validate_receipt_identity", "detect_duplicate_report"], purpose="data_quality"), "demo")
    from cbcr_platform import runs as run_module
    handlers = dict(run_module.HANDLERS)
    handlers.pop("validate_receipt_identity")
    monkeypatch.setattr(run_module, "HANDLERS", handlers)
    drain(runs)
    statuses = {row["function_code"]: row["status"] for row in runs.get(run_id)["function_runs"]}
    assert statuses == {"detect_duplicate_report": "succeeded", "validate_receipt_identity": "failed"}
    assert runs.get(run_id)["status"] == "completed_with_errors"


def test_raw_snapshots_cannot_be_changed_or_deleted(services):
    db, _, runs = services
    run_id = runs.create(RunRequest(source_id="fixture_alpha", functions=["validate_receipt_identity"], purpose="data_quality"), "demo")
    drain(runs)
    snapshot = db.one("SELECT snapshot_id FROM raw_snapshots WHERE run_id=?", (run_id,))
    for sql in ("UPDATE raw_snapshots SET payload_json='{}' WHERE snapshot_id=?",
                "DELETE FROM raw_snapshots WHERE snapshot_id=?"):
        try:
            db.execute(sql, (snapshot["snapshot_id"],))
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("raw snapshot mutation should be rejected")
