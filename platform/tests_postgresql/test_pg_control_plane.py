from __future__ import annotations

import uuid

from test_pg_acceptance import response_value


def test_user_multi_role_assignment_and_effective_union(pg_runtime, drain_queue):
    client, _ = pg_runtime
    user_id = f"acceptance-{uuid.uuid4()}"
    response_value(
        client.post(
            "/api/v1/users", json={"user_id": user_id, "display_name": "Acceptance User"}
        ),
        201,
    )
    assigned = response_value(
        client.put(
            f"/api/v1/users/{user_id}/roles",
            json={"role_ids": ["dq_analyst", "risk_analyst"]},
        )
    )
    assert assigned["role_count"] == 2
    users = response_value(client.get("/api/v1/users"))
    user = next(row for row in users if row["user_id"] == user_id)
    assert set(user["roles"]) == {"dq_analyst", "risk_analyst"}
    headers = {"X-CbCR-User": user_id}
    queued = response_value(
        client.post(
            "/api/v1/runs",
            headers=headers,
            json={
                "source_id": "fixture_alpha",
                "functions": ["validate_receipt_identity"],
                "parameters": {},
                "purpose": "data_quality",
            },
        ),
        202,
    )
    drain_queue()
    assert response_value(client.get(queued["status_url"], headers=headers))["status"] == "completed"
    risk = response_value(
        client.post(
            "/api/v1/runs",
            headers=headers,
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
    assert response_value(client.get(risk["status_url"], headers=headers))["status"] == "completed"


def test_function_draft_activate_retire_and_reject_unknown_handler(pg_runtime):
    client, _ = pg_runtime
    code = "acceptance_" + uuid.uuid4().hex[:12]
    created = response_value(
        client.post(
            "/api/v1/functions",
            json={
                "code": code,
                "stage": "01",
                "name": "Acceptance function",
                "description": "Lifecycle acceptance",
                "handler": "validate_receipt_identity",
                "purpose": "data_quality",
                "parameter_schema": {},
            },
        ),
        201,
    )
    assert created["lifecycle"] == "draft"
    assert client.post(f"/api/v1/functions/{code}/versions/1/activate").status_code == 200
    assert client.post(f"/api/v1/functions/{code}/versions/1/retire").status_code == 200

    bad_code = "acceptance_" + uuid.uuid4().hex[:12]
    response_value(
        client.post(
            "/api/v1/functions",
            json={
                "code": bad_code,
                "stage": "01",
                "name": "Unavailable function",
                "description": "Must not activate",
                "handler": "handler_not_installed",
                "purpose": "data_quality",
                "parameter_schema": {},
            },
        ),
        201,
    )
    assert client.post(f"/api/v1/functions/{bad_code}/versions/1/activate").status_code == 409
    assert client.delete(f"/api/v1/functions/{bad_code}/versions/1").status_code == 204


def test_source_secret_and_identifier_validation(pg_runtime):
    client, _ = pg_runtime
    source_id = "acceptance-" + uuid.uuid4().hex[:12]
    embedded = client.put(
        f"/api/v1/sources/{source_id}",
        json={
            "source_id": source_id,
            "name": "Unsafe source",
            "adapter_type": "postgresql-canonical",
            "endpoint_link": "postgresql://user:plain-secret@localhost/cbcr?view=cbcr_canonical.v_api_report_json",
            "secret_ref": "env:CBCR_SOURCE_DB_PASSWORD",
        },
    )
    assert embedded.status_code == 422
    unsafe_view = client.put(
        f"/api/v1/sources/{source_id}",
        json={
            "source_id": source_id,
            "name": "Unsafe source",
            "adapter_type": "postgresql-canonical",
            "endpoint_link": "postgresql://user@localhost/cbcr?view=cbcr_canonical.v_api_report_json%3BDROP",
            "secret_ref": "env:CBCR_SOURCE_DB_PASSWORD",
        },
    )
    assert unsafe_view.status_code == 422


def test_mapping_validation_and_dictionary_contract(pg_runtime):
    client, _ = pg_runtime
    profile_id = "acceptance-" + uuid.uuid4().hex[:12]
    response_value(
        client.post(
            "/api/v1/mappings",
            json={
                "profile_id": profile_id,
                "source_id": "fixture_alpha",
                "version": 1,
                "mapping": {"report": {"report_id": "report_key"}},
            },
        ),
        201,
    )
    validation = response_value(
        client.get(f"/api/v1/mappings/{profile_id}/versions/1/validate")
    )
    assert not validation["valid"] and validation["missing_required_fields"]
    assert client.post(f"/api/v1/mappings/{profile_id}/versions/1/activate").status_code == 409
    dictionary = response_value(client.get("/api/v1/data-dictionary/canonical"))
    assert any(
        row["logical_object"] == "report" and row["canonical_field"] == "report_id"
        for row in dictionary
    )
