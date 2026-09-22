from __future__ import annotations

from fastapi.testclient import TestClient


def test_api_exposes_catalogue_and_accepts_run(monkeypatch, tmp_path):
    from cbcr_platform import api
    replacement = api.Container(tmp_path / "api.db")
    monkeypatch.setattr(api, "container", replacement)
    with TestClient(api.app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert len(client.get("/api/v1/functions").json()) == 14
        assert len(client.get("/api/v1/functions?lifecycle=").json()) == 14
        response = client.post("/api/v1/runs", json={
            "source_id": "fixture_beta", "functions": ["check_completeness"],
            "parameters": {}, "purpose": "data_quality"
        })
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        for _ in range(50):
            value = client.get(f"/api/v1/runs/{run_id}").json()
            if value["status"].startswith("completed"):
                break
        assert value["status"] == "completed"


def test_access_control_blocks_auditor_from_run(monkeypatch, tmp_path):
    from cbcr_platform import api
    monkeypatch.setattr(api, "container", api.Container(tmp_path / "denied.db"))
    with TestClient(api.app) as client:
        response = client.post("/api/v1/runs", headers={"x-cbcr-user": "auditor"}, json={
            "source_id": "fixture_alpha", "functions": ["check_completeness"],
            "purpose": "data_quality"
        })
        assert response.status_code == 403


def test_case_manager_can_view_stage_07_but_not_other_runs(monkeypatch, tmp_path):
    from cbcr_platform import api
    replacement = api.Container(tmp_path / "case.db")
    replacement.db.execute("INSERT INTO users VALUES('case_user','Case user',1,'now')")
    replacement.db.execute("INSERT INTO user_roles VALUES('case_user','case_manager','now')")
    monkeypatch.setattr(api, "container", replacement)
    with TestClient(api.app) as client:
        run = client.post("/api/v1/runs", headers={"x-cbcr-user": "case_user"}, json={
            "source_id": "fixture_alpha", "functions": ["create_selection_report"],
            "purpose": "case_review"
        })
        assert run.status_code == 202
        run_id = run.json()["run_id"]
        assert client.get(f"/api/v1/runs/{run_id}", headers={"x-cbcr-user": "case_user"}).status_code == 200
        assert {row["run_id"] for row in client.get("/api/v1/runs", headers={"x-cbcr-user": "case_user"}).json()} == {run_id}


def test_unknown_identity_cannot_enumerate_sources_or_catalogue(monkeypatch, tmp_path):
    from cbcr_platform import api
    monkeypatch.setattr(api, "container", api.Container(tmp_path / "identity.db"))
    with TestClient(api.app) as client:
        headers = {"x-cbcr-user": "not-a-user"}
        assert client.get("/api/v1/sources", headers=headers).status_code == 403
        assert client.get("/api/v1/functions", headers=headers).status_code == 403


def test_function_lifecycle_requires_an_installed_handler(monkeypatch, tmp_path):
    from cbcr_platform import api
    monkeypatch.setattr(api, "container", api.Container(tmp_path / "lifecycle.db"))
    with TestClient(api.app) as client:
        draft = client.post("/api/v1/functions", json={
            "code": "future_quality_function", "stage": "04", "name": "Future function",
            "description": "Awaiting a deployed implementation.", "handler": "not_installed",
            "purpose": "data_quality", "parameter_schema": {}, "output_classification": "restricted"
        })
        assert draft.status_code == 201
        activation = client.post("/api/v1/functions/future_quality_function/versions/1/activate")
        assert activation.status_code == 409
        assert "not installed" in activation.json()["detail"]
        all_versions = client.get("/api/v1/functions?lifecycle=").json()
        assert any(row["code"] == "future_quality_function" and row["lifecycle"] == "draft" for row in all_versions)
