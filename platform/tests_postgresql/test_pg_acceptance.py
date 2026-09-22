from __future__ import annotations

import json
import uuid

import pytest


def response_value(response, expected: int = 200):
    assert response.status_code == expected, response.text
    return response.json()


def queue_dataset_run(client, drain, dataset_id, zone, functions, purpose, parameters=None):
    value = response_value(
        client.post(
            "/api/v1/dataset-runs",
            json={
                "dataset_id": dataset_id,
                "dataset_version": 1,
                "input_zone": zone,
                "functions": functions,
                "parameters": parameters or {},
                "purpose": purpose,
            },
        ),
        202,
    )
    claims = drain()
    run = response_value(client.get(value["status_url"]))
    assert run["status"] == "completed", run
    assert all(child["status"] == "succeeded" for child in run["function_runs"])
    return run, claims


@pytest.fixture(scope="session")
def journey(pg_runtime, drain_queue):
    client, container = pg_runtime
    lot = response_value(
        client.post(
            "/api/v1/lots",
            json={
                "source_id": "fixture_alpha",
                "pipeline_profile_id": "ideal_separated",
                "external_lot_ref": f"pg-acceptance-{uuid.uuid4()}",
                "metadata": {"test_suite": "postgresql-acceptance"},
            },
        ),
        201,
    )
    canonical_id = lot["canonical_dataset"]["dataset_id"]
    canonical_reports = response_value(
        client.get(f"/api/v1/datasets/{canonical_id}/versions/1/reports")
    )
    report_id = canonical_reports[0]["report_id"]
    stage_runs = {}
    claimed = []
    for stage, functions in {
        "01": ["validate_receipt_identity", "detect_duplicate_report"],
        "02": ["normalize_currency", "standardize_identifiers"],
        "03": ["resolve_entity", "enrich_jurisdiction_reference"],
        "04": ["check_completeness", "check_rpt_share_threshold"],
    }.items():
        stage_runs[stage], stage_claims = queue_dataset_run(
            client, drain_queue, canonical_id, "canonical", functions, "data_quality"
        )
        claimed.extend(stage_claims)

    evaluation = response_value(
        client.post(
            f"/api/v1/datasets/{canonical_id}/versions/1/evaluate-promotion",
            json={
                "run_id": stage_runs["04"]["run_id"],
                "blocking_severities": ["error"],
            },
        ),
        201,
    )
    dq_passed = response_value(
        client.post(
            f"/api/v1/datasets/{canonical_id}/versions/1/promote",
            json={
                "target_zone": "dq_passed",
                "evaluation_id": evaluation["evaluation_id"],
                "reason": "PostgreSQL acceptance DQ gate",
            },
        ),
        201,
    )
    enriched = response_value(
        client.post(
            f"/api/v1/datasets/{dq_passed['target_dataset_id']}/versions/1/promote",
            json={
                "target_zone": "enriched",
                "reason": "PostgreSQL acceptance enrichment",
                "enrichment_values": [
                    {
                        "report_id": report_id,
                        "attribute_name": "acceptance_classification",
                        "value": "verified",
                        "source_ref": "acceptance-suite",
                        "confidence": 1.0,
                    }
                ],
            },
        ),
        201,
    )
    risk_ready = response_value(
        client.post(
            f"/api/v1/datasets/{enriched['target_dataset_id']}/versions/1/promote",
            json={"target_zone": "risk_ready", "reason": "PostgreSQL acceptance publication"},
        ),
        201,
    )
    risk_run, risk_claims = queue_dataset_run(
        client,
        drain_queue,
        risk_ready["target_dataset_id"],
        "risk_ready",
        ["analyze_profit_presence_mismatch", "analyze_etr_outlier"],
        "risk_assessment",
    )
    score_run, score_claims = queue_dataset_run(
        client,
        drain_queue,
        risk_ready["target_dataset_id"],
        "risk_ready",
        ["cross_match_domestic_turnover", "score_risk_components"],
        "risk_assessment",
    )
    case_run, case_claims = queue_dataset_run(
        client,
        drain_queue,
        risk_ready["target_dataset_id"],
        "risk_ready",
        ["generate_case_candidates", "create_selection_report"],
        "case_review",
    )
    claimed.extend(risk_claims + score_claims + case_claims)
    batches = response_value(client.get("/api/v1/selection-batches"))
    batch = next(row for row in batches if row["run_id"] == case_run["run_id"])
    candidates = response_value(
        client.get(f"/api/v1/selection-batches/{batch['selection_batch_id']}/candidates")
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    response_value(
        client.put(
            f"/api/v1/selection-candidates/{candidate['candidate_id']}/decision",
            json={
                "decision": "selected",
                "rationale": "Selected by the PostgreSQL acceptance journey",
            },
        )
    )
    return {
        "lot": lot,
        "canonical_id": canonical_id,
        "report_id": report_id,
        "stage_runs": stage_runs,
        "evaluation": evaluation,
        "dq_passed": dq_passed,
        "enriched": enriched,
        "risk_ready": risk_ready,
        "risk_run": risk_run,
        "score_run": score_run,
        "case_run": case_run,
        "batch": batch,
        "candidate": candidate,
        "claims": claimed,
    }


def test_schema_configuration_bootstrap_and_contract(pg_runtime):
    client, container = pg_runtime
    health = response_value(client.get("/api/v1/health"))
    assert health["persistence_backend"] == "postgresql"
    assert health["database"]["database"]
    assert "password" not in json.dumps(health).lower()
    migrations = container.db.all(
        "SELECT migration_id FROM cbcr_control.schema_migration ORDER BY migration_id"
    )
    assert "004_postgresql_runtime_alignment" in {row["migration_id"] for row in migrations}
    schemas = container.db.all(
        "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'cbcr_%'"
    )
    assert len(schemas) == 9
    functions = response_value(client.get("/api/v1/functions"))
    assert len(functions) == 14
    assert len({row["code"] for row in functions}) == 14
    sources = response_value(client.get("/api/v1/sources"))
    assert {"fixture_alpha", "fixture_beta", "local_cbcr_postgresql"} <= {
        row["source_id"] for row in sources
    }
    assert "Qwerty" not in json.dumps(sources)

    from cbcr_platform.api import app as sqlite_app
    from cbcr_platform_pg.api import app as pg_app

    sqlite_paths = sqlite_app.openapi()["paths"]
    pg_paths = pg_app.openapi()["paths"]
    assert set(sqlite_paths) == set(pg_paths)
    for path in sqlite_paths:
        assert set(sqlite_paths[path]) == set(pg_paths[path])


def test_access_validation_and_safe_failures(pg_runtime, journey):
    client, _ = pg_runtime
    unknown = {"X-CbCR-User": f"unknown-{uuid.uuid4()}"}
    assert client.get("/api/v1/sources", headers=unknown).status_code == 403
    assert client.get("/api/v1/audit", headers={"X-CbCR-User": "auditor"}).status_code == 200
    canonical_id = journey["canonical_id"]
    base = {
        "dataset_id": canonical_id,
        "dataset_version": 1,
        "input_zone": "canonical",
        "functions": ["check_completeness"],
        "purpose": "data_quality",
    }
    bad = dict(base, parameters={"check_completeness": {"unknown_parameter": True}})
    assert client.post("/api/v1/dataset-runs", json=bad).status_code == 422
    risk_on_canonical = dict(
        base,
        functions=["analyze_etr_outlier"],
        parameters={},
        purpose="risk_assessment",
    )
    assert client.post("/api/v1/dataset-runs", json=risk_on_canonical).status_code == 422
    assert client.get("/api/v1/audit", params={"limit": 1001}).status_code == 422


def test_local_postgresql_source_uses_canonical_api(pg_runtime, drain_queue):
    client, container = pg_runtime
    lot = response_value(
        client.post(
            "/api/v1/lots",
            json={
                "source_id": "local_cbcr_postgresql",
                "pipeline_profile_id": "ideal_separated",
                "external_lot_ref": f"pg-source-acceptance-{uuid.uuid4()}",
                "metadata": {"test_suite": "postgresql-source-acceptance"},
            },
        ),
        201,
    )
    assert lot["report_count"] == 4
    dataset_id = lot["canonical_dataset"]["dataset_id"]
    reports = response_value(client.get(f"/api/v1/datasets/{dataset_id}/versions/1/reports"))
    assert len(reports) == 4
    assert all("reporting_entity_id" in report for report in reports)
    assert container.db.one(
        "SELECT count(*)::int AS count FROM cbcr_staging.source_record WHERE dataset_id=%s",
        (lot["landing_dataset"]["dataset_id"],),
    )["count"] == 4
    run, _ = queue_dataset_run(
        client,
        drain_queue,
        dataset_id,
        "canonical",
        ["validate_receipt_identity"],
        "data_quality",
    )
    assert run["function_runs"][0]["summary"]["reports_checked"] == 4


def test_complete_lifecycle_rule_outputs_and_lineage(pg_runtime, journey):
    client, container = pg_runtime
    assert journey["lot"]["report_count"] == 1
    reports = response_value(
        client.get(f"/api/v1/datasets/{journey['canonical_id']}/versions/1/reports")
    )
    assert len(reports) == 1 and reports[0]["report_id"] == journey["report_id"]

    expected_findings = {"01": 0, "02": 0, "03": 1, "04": 1}
    for stage, count in expected_findings.items():
        findings = response_value(
            client.get(f"/api/v1/runs/{journey['stage_runs'][stage]['run_id']}/findings")
        )
        assert len(findings) == count
        assert all(row["function_run_id"] for row in findings)
    stage02 = journey["stage_runs"]["02"]
    normalize = next(
        child for child in stage02["function_runs"] if child["function_code"] == "normalize_currency"
    )
    assert len(normalize["artifacts"]) == 1

    assert journey["evaluation"]["eligible_count"] == 1
    assert journey["evaluation"]["rejected_count"] == 0
    dispositions = response_value(
        client.get(f"/api/v1/evaluations/{journey['evaluation']['evaluation_id']}/dispositions")
    )
    assert len(dispositions) == 1 and dispositions[0]["disposition"] == "eligible"
    assert journey["dq_passed"]["promoted_count"] == 1
    assert journey["enriched"]["promoted_count"] == 1
    assert journey["risk_ready"]["promoted_count"] == 1

    zones = container.db.all(
        """SELECT zone,report_count FROM cbcr_control.dataset
           WHERE dataset_id IN (%s,%s,%s,%s)""",
        (
            journey["canonical_id"],
            journey["dq_passed"]["target_dataset_id"],
            journey["enriched"]["target_dataset_id"],
            journey["risk_ready"]["target_dataset_id"],
        ),
    )
    assert {row["zone"] for row in zones} == {
        "canonical",
        "dq_passed",
        "enriched",
        "risk_ready",
    }
    assert all(row["report_count"] == 1 for row in zones)
    lineage_count = container.db.one(
        """SELECT count(*)::int AS count FROM cbcr_control.dataset_lineage
           WHERE child_dataset_id IN (%s,%s,%s,%s)""",
        (
            journey["canonical_id"],
            journey["dq_passed"]["target_dataset_id"],
            journey["enriched"]["target_dataset_id"],
            journey["risk_ready"]["target_dataset_id"],
        ),
    )["count"]
    assert lineage_count == 4
    enrichment_count = container.db.one(
        "SELECT count(*)::int AS count FROM cbcr_enriched.attribute WHERE dataset_id=%s",
        (journey["enriched"]["target_dataset_id"],),
    )["count"]
    assert enrichment_count == 1


def test_risk_selection_provenance_and_decision_history(pg_runtime, journey):
    client, container = pg_runtime
    stage05 = response_value(
        client.get("/api/v1/risk-results", params={"run_id": journey["risk_run"]["run_id"]})
    )
    assert len(stage05) == 2
    assert all(row["function_run_id"] for row in stage05)
    stage06 = response_value(
        client.get("/api/v1/risk-results", params={"run_id": journey["score_run"]["run_id"]})
    )
    assert len(stage06) == 2
    assert any(row["score_components"] for row in stage06)
    candidate = container.db.one(
        "SELECT decision,decision_rationale FROM cbcr_selection.candidate WHERE candidate_id=%s",
        (journey["candidate"]["candidate_id"],),
    )
    assert candidate["decision"] == "selected"
    assert candidate["decision_rationale"]
    history = container.db.one(
        "SELECT count(*)::int AS count FROM cbcr_selection.decision_history WHERE candidate_id=%s",
        (journey["candidate"]["candidate_id"],),
    )
    assert history["count"] == 1
    missing_rationale = client.put(
        f"/api/v1/selection-candidates/{journey['candidate']['candidate_id']}/decision",
        json={"decision": "deferred", "rationale": ""},
    )
    assert missing_rationale.status_code == 422


def test_two_worker_exactly_once_and_lease_recovery(pg_runtime, drain_queue, journey):
    client, container = pg_runtime
    run, claims = queue_dataset_run(
        client,
        drain_queue,
        journey["canonical_id"],
        "canonical",
        [
            "validate_receipt_identity",
            "detect_duplicate_report",
            "normalize_currency",
            "standardize_identifiers",
            "resolve_entity",
            "enrich_jurisdiction_reference",
            "check_completeness",
            "check_rpt_share_threshold",
        ],
        "data_quality",
    )
    claimed_ids = [item[0] for item in claims]
    assert len(claimed_ids) == 8 and len(set(claimed_ids)) == 8
    children = container.db.all(
        "SELECT function_run_id,attempt,status FROM cbcr_control.function_run WHERE run_id=%s",
        (run["run_id"],),
    )
    assert len(children) == 8
    assert all(row["attempt"] == 1 and row["status"] == "succeeded" for row in children)

    queued = response_value(
        client.post(
            "/api/v1/dataset-runs",
            json={
                "dataset_id": journey["canonical_id"],
                "dataset_version": 1,
                "input_zone": "canonical",
                "functions": ["validate_receipt_identity"],
                "parameters": {},
                "purpose": "data_quality",
            },
        ),
        202,
    )
    claimed = container.runs.claim_next("acceptance-crashed-worker")
    assert claimed and str(claimed["run_id"]) == queued["run_id"]
    container.db.execute(
        """UPDATE cbcr_control.function_run
           SET lease_expires_at=clock_timestamp()-interval '1 second'
           WHERE function_run_id=%s""",
        (claimed["function_run_id"],),
    )
    assert container.runs.recover_expired() == 1
    drain_queue()
    recovered = response_value(client.get(queued["status_url"]))
    assert recovered["status"] == "completed"
    assert recovered["function_runs"][0]["attempts"] == 2


def test_idempotence_immutability_audit_and_direct_compatibility(pg_runtime, drain_queue, journey):
    client, container = pg_runtime
    repeated = response_value(
        client.post(
            f"/api/v1/datasets/{journey['canonical_id']}/versions/1/promote",
            json={
                "target_zone": "dq_passed",
                "evaluation_id": journey["evaluation"]["evaluation_id"],
                "reason": "repeat must be idempotent",
            },
        ),
        201,
    )
    assert repeated["target_dataset_id"] == journey["dq_passed"]["target_dataset_id"]
    with pytest.raises(Exception):
        container.db.execute(
            """UPDATE cbcr_canonical.report SET reporting_entity_name='mutated'
               WHERE dataset_id=%s""",
            (journey["canonical_id"],),
        )
    with pytest.raises(Exception):
        container.db.execute(
            """DELETE FROM cbcr_staging.source_record
               WHERE lot_id=%s""",
            (journey["lot"]["lot_id"],),
        )
    audit = response_value(
        client.get(
            "/api/v1/audit",
            params={"limit": 1000},
            headers={"X-CbCR-User": "auditor"},
        )
    )
    actions = {row["action"] for row in audit}
    assert {"INGEST_LOT", "CREATE_DATASET_RUN", "DECIDE_CANDIDATE"} <= actions
    assert "Qwerty" not in json.dumps(audit)

    direct = response_value(
        client.post(
            "/api/v1/runs",
            json={
                "source_id": "fixture_alpha",
                "functions": ["analyze_etr_outlier"],
                "parameters": {},
                "purpose": "risk_assessment",
            },
        ),
        202,
    )
    drain_queue()
    direct_run = response_value(client.get(direct["status_url"]))
    assert direct_run["status"] == "completed"
    assert direct_run["input_zone"] == "risk_ready"
