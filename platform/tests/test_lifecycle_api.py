from __future__ import annotations

import time

from fastapi.testclient import TestClient


def wait_for_run(client: TestClient, run_id: str):
    for _ in range(100):
        value = client.get(f"/api/v1/runs/{run_id}").json()
        if value["status"].startswith("completed"):
            return value
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_api_poc_from_landing_to_selection_decision(monkeypatch, tmp_path):
    from cbcr_platform import api
    monkeypatch.setattr(api, "container", api.Container(tmp_path / "lifecycle-api.db"))
    with TestClient(api.app) as client:
        assert len(client.get("/api/v1/data-dictionary/canonical").json()) >= 20
        mapping = client.get("/api/v1/mappings/alpha_v1/versions/1/validate").json()
        assert mapping["valid"]
        assert client.get("/api/v1/mappings/alpha_v1/versions/1/dictionary").json()
        profiles = client.get("/api/v1/pipeline-profiles").json()
        assert {profile["profile_id"] for profile in profiles} == {
            "ideal_separated", "combined_enrichment", "trusted_prevalidated"
        }

        ingested = client.post("/api/v1/lots", json={
            "source_id": "fixture_alpha", "pipeline_profile_id": "ideal_separated",
            "external_lot_ref": "POC-LOT-001"
        })
        assert ingested.status_code == 201
        canonical_id = ingested.json()["canonical_dataset"]["dataset_id"]

        dq = client.post("/api/v1/dataset-runs", json={
            "dataset_id": canonical_id, "dataset_version": 1, "input_zone": "canonical",
            "functions": ["check_completeness", "check_rpt_share_threshold"],
            "parameters": {}, "purpose": "data_quality"
        })
        assert dq.status_code == 202
        wait_for_run(client, dq.json()["run_id"])
        evaluation = client.post(f"/api/v1/datasets/{canonical_id}/versions/1/evaluate-promotion", json={
            "run_id": dq.json()["run_id"], "blocking_severities": ["error"]
        }).json()
        assert evaluation["eligible_count"] == 1

        passed = client.post(f"/api/v1/datasets/{canonical_id}/versions/1/promote", json={
            "target_zone": "dq_passed", "evaluation_id": evaluation["evaluation_id"]
        }).json()
        enriched = client.post(f"/api/v1/datasets/{passed['target_dataset_id']}/versions/1/promote", json={
            "target_zone": "enriched", "enrichment_values": [{
                "report_id": "RPT-2025-001", "entity_id": "ENT-IN-01",
                "attribute_name": "registry_status", "value": "active",
                "source_ref": "registry:demo", "confidence": 0.98
            }]
        }).json()
        ready = client.post(f"/api/v1/datasets/{enriched['target_dataset_id']}/versions/1/promote", json={
            "target_zone": "risk_ready", "reason": "Enrichment approved"
        }).json()

        risk = client.post("/api/v1/dataset-runs", json={
            "dataset_id": ready["target_dataset_id"], "dataset_version": 1,
            "input_zone": "risk_ready", "functions": ["analyze_etr_outlier", "score_risk_components"],
            "parameters": {}, "purpose": "risk_assessment"
        })
        wait_for_run(client, risk.json()["run_id"])
        assert client.get(f"/api/v1/risk-results?run_id={risk.json()['run_id']}").json()

        selection = client.post("/api/v1/dataset-runs", json={
            "dataset_id": ready["target_dataset_id"], "dataset_version": 1,
            "input_zone": "risk_ready", "functions": ["generate_case_candidates"],
            "parameters": {}, "purpose": "case_review"
        })
        wait_for_run(client, selection.json()["run_id"])
        batch = client.get("/api/v1/selection-batches").json()[0]
        candidate = client.get(f"/api/v1/selection-batches/{batch['selection_batch_id']}/candidates").json()[0]
        decision = client.put(f"/api/v1/selection-candidates/{candidate['candidate_id']}/decision", json={
            "decision": "selected", "rationale": "PoC review decision"
        })
        assert decision.json()["decision"] == "selected"

        zones = [dataset["zone"] for dataset in client.get("/api/v1/datasets").json()]
        assert zones == ["landing", "canonical", "dq_passed", "enriched", "risk_ready"]
