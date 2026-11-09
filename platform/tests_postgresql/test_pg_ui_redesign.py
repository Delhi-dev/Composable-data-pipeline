from __future__ import annotations


def test_standard_ui_routes_and_advanced_fallback(pg_runtime):
    client, _ = pg_runtime
    standard = client.get("/")
    advanced = client.get("/advanced")
    deep_link = client.get("/runs/not-a-real-run")
    assert standard.status_code == 200
    assert "/assets/app/main.js" in standard.text
    assert advanced.status_code == 200
    assert "/assets/niche.js" in advanced.text
    assert deep_link.status_code == 200


def test_redesign_support_apis_are_queryable(pg_runtime):
    client, _ = pg_runtime
    me = client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["roles"]

    dashboard = client.get("/api/v1/dashboard", params={"days": 30})
    assert dashboard.status_code == 200
    assert set(dashboard.json()["cards"]) >= {
        "failed_runs", "active_runs", "awaiting_dq_run", "awaiting_dq_gate",
        "awaiting_publication", "awaiting_evidence_approval", "pending_case_decisions",
    }

    for path, params in (
        ("/api/v1/lots", {"page_size": 2, "q": "unlikely-to-match"}),
        ("/api/v1/datasets", {"page_size": 2, "zone": "canonical"}),
        ("/api/v1/runs", {"page_size": 2, "status": "completed"}),
        ("/api/v1/selection-batches", {"scope": "all"}),
        ("/api/v1/case-sets", {"scope": "all"}),
    ):
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)


def test_risk_evidence_set_summaries_include_run_provenance(pg_runtime):
    client, _ = pg_runtime
    response = client.get("/api/v1/risk-result-sets", params={"scope": "all"})
    assert response.status_code == 200
    for value in response.json():
        assert "run_ids" in value
        assert "runs" in value


def test_platform_admin_can_read_audit_and_case_scope_is_available(pg_runtime):
    client, _ = pg_runtime
    audit = client.get("/api/v1/audit", params={"limit": 1})
    assert audit.status_code == 200, audit.text
    datasets = client.get(
        "/api/v1/datasets",
        params={"zone": "risk_ready", "scope": "case_workbench", "page_size": 2},
    )
    assert datasets.status_code == 200, datasets.text


def test_dataset_detail_includes_lot_context(pg_runtime):
    client, _ = pg_runtime
    datasets = client.get("/api/v1/datasets", params={"page_size": 1}).json()
    if not datasets:
        return
    value = datasets[0]
    detail = client.get(
        f"/api/v1/datasets/{value['dataset_id']}/versions/{value['version']}"
    )
    assert detail.status_code == 200, detail.text
    assert "external_lot_ref" in detail.json()
