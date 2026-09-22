from __future__ import annotations

import sqlite3

from cbcr_platform.contracts import DatasetRunRequest, EnrichmentValue
from cbcr_platform.data_plane import DataPlaneService


def drain(service):
    while service.process_one():
        pass


def test_complete_zone_lifecycle_persists_business_outputs(services):
    db, _, runs = services
    data = runs.data_plane
    ingested = data.ingest("fixture_alpha", "demo", pipeline_profile_id="ideal_separated")
    canonical_id = ingested["canonical_dataset"]["dataset_id"]

    dq_run = runs.create_dataset_run(DatasetRunRequest(
        dataset_id=canonical_id, input_zone="canonical", purpose="data_quality",
        functions=["check_completeness", "check_rpt_share_threshold"],
    ), "demo")
    drain(runs)
    assert runs.get(dq_run)["status"] == "completed"

    evaluation = data.evaluate(dq_run, ["error"], "demo")
    assert evaluation == {"evaluation_id": evaluation["evaluation_id"],
                          "eligible_count": 1, "rejected_count": 0}
    dq_passed = data.promote(canonical_id, 1, "dq_passed", "demo",
                             evaluation["evaluation_id"], reason="DQ gate passed")
    assert dq_passed["promoted_count"] == 1

    enriched = data.promote(dq_passed["target_dataset_id"], 1, "enriched", "demo",
        enrichment_values=[EnrichmentValue(report_id="RPT-2025-001", entity_id="ENT-IN-01",
            attribute_name="domestic_registry_status", value="active",
            source_ref="domestic-registry:TIN-AAECA1234F", confidence=0.99)])
    risk_ready = data.promote(enriched["target_dataset_id"], 1, "risk_ready", "demo",
                              reason="Enrichment review complete")
    rr_id = risk_ready["target_dataset_id"]

    risk_run = runs.create_dataset_run(DatasetRunRequest(
        dataset_id=rr_id, input_zone="risk_ready", purpose="risk_assessment",
        functions=["analyze_etr_outlier", "score_risk_components"],
    ), "demo")
    drain(runs)
    assert runs.get(risk_run)["status"] == "completed"
    assert db.one("SELECT COUNT(*) AS n FROM risk_results WHERE run_id=?", (risk_run,))["n"] >= 2
    assert db.one("SELECT COUNT(*) AS n FROM risk_score_components", ())["n"] == 1

    selection_run = runs.create_dataset_run(DatasetRunRequest(
        dataset_id=rr_id, input_zone="risk_ready", purpose="case_review",
        functions=["generate_case_candidates"],
    ), "demo")
    drain(runs)
    candidate = db.one("SELECT * FROM selection_candidates")
    assert candidate["report_id"] == "RPT-2025-001"
    assert candidate["decision"] == "pending"

    zones = [row["zone"] for row in data.list_datasets(ingested["lot_id"])]
    assert zones == ["landing", "canonical", "dq_passed", "enriched", "risk_ready"]
    assert db.one("SELECT COUNT(*) AS n FROM enrichment_attributes", ())["n"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM dataset_lineage", ())["n"] == 4


def test_risk_cannot_run_before_risk_ready(services):
    _, _, runs = services
    canonical = runs.data_plane.ingest("fixture_alpha", "demo")["canonical_dataset"]["dataset_id"]
    try:
        runs.create_dataset_run(DatasetRunRequest(
            dataset_id=canonical, input_zone="canonical", purpose="risk_assessment",
            functions=["analyze_etr_outlier"],
        ), "demo")
    except ValueError as exc:
        assert "cannot consume canonical" in str(exc) or "risk_ready" in str(exc)
    else:
        raise AssertionError("risk functions must not consume canonical working data")


def test_combined_profile_skips_enrichment_as_a_physical_transition(services):
    _, _, runs = services
    data: DataPlaneService = runs.data_plane
    canonical = data.ingest("fixture_beta", "demo",
                            pipeline_profile_id="combined_enrichment")["canonical_dataset"]["dataset_id"]
    dq_run = runs.create_dataset_run(DatasetRunRequest(
        dataset_id=canonical, input_zone="canonical", purpose="data_quality",
        functions=["check_completeness"],
    ), "demo")
    drain(runs)
    evaluation = data.evaluate(dq_run, ["error"], "demo")
    passed = data.promote(canonical, 1, "dq_passed", "demo", evaluation["evaluation_id"])
    final = data.promote(passed["target_dataset_id"], 1, "risk_ready", "demo",
                         reason="Enrichment is upstream/combined under this profile")
    assert final["target_zone"] == "risk_ready"
    assert [row["zone"] for row in data.list_datasets()] == [
        "landing", "canonical", "dq_passed", "risk_ready"
    ]


def test_published_business_zone_rows_are_database_immutable(services):
    db, _, runs = services
    canonical = runs.data_plane.ingest("fixture_alpha", "demo")["canonical_dataset"]["dataset_id"]
    try:
        db.execute("UPDATE can_reports SET reporting_entity_name='Changed' WHERE dataset_id=?",
                   (canonical,))
    except sqlite3.IntegrityError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("published canonical rows must be immutable")
