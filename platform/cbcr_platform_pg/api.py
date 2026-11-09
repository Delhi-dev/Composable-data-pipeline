from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from cbcr_platform.contracts import (
    AuditCaseStatusRequest,
    CaseSetFinalizeRequest,
    DatasetRunRequest,
    FunctionDraft,
    GateEvaluationRequest,
    LotIngestRequest,
    MappingDictionaryRequest,
    MappingProfileCreate,
    PipelineProfileRequest,
    PromotionRequest,
    RoleAssignment,
    RiskResultSetApproval,
    RiskResultSetCreate,
    RunRequest,
    SelectionDecisionRequest,
    SourceCreate,
    UserCreate,
    UserStatusRequest,
)
from cbcr_platform.dictionary import canonical_dictionary
from cbcr_platform.function_library import HANDLERS

from .access import AccessDenied
from .admin import AdminConflict, AdminNotFound
from .catalog import ConflictError
from .case_handoff import CaseHandoffError
from .container import PostgreSQLContainer
from .data_plane import DataPlaneError
from .database import new_uuid, utc_now
from .runs import RunValidationError
from .risk_result_sets import RiskResultSetError
from .reports import CaseReportError


container = PostgreSQLContainer()


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(container.worker.run())
    yield
    container.worker.stop()
    await task
    container.close()


app = FastAPI(title="CbCR DB-First Control Plane", version="0.2.0-pg", lifespan=lifespan)
static_root = Path(__file__).resolve().parents[1] / "cbcr_platform" / "web"
app.mount("/assets", StaticFiles(directory=static_root), name="assets")


def actor(x_cbcr_user: Annotated[str | None, Header()] = None) -> str:
    return x_cbcr_user or "demo"


def require(
    user: str, action: str, *, stage: str | None = None, purpose: str | None = None
) -> None:
    try:
        container.access.require(user, action, stage=stage, purpose=purpose)
    except AccessDenied as exc:
        container.db.audit(
            new_uuid(),
            user,
            action,
            stage or "platform",
            "denied",
            purpose,
            {"reason": str(exc)},
        )
        raise HTTPException(403, str(exc)) from exc


def may_view_run(user: str, value: dict) -> bool:
    stages = {child["stage"] for child in value.get("function_runs", [])}
    return bool(stages) and all(
        container.access.decide(
            user, "view_results", stage=stage, purpose=value["purpose"]
        ).allowed
        for stage in stages
    )


def require_run_view(user: str, value: dict) -> None:
    if not may_view_run(user, value):
        raise HTTPException(403, "view_results denied for one or more run stages")


def require_case_view(user: str) -> None:
    case_access = container.access.decide(
        user, "view_results", stage="07", purpose="case_review"
    ).allowed
    audit_access = container.access.decide(user, "view_audit").allowed
    if not (case_access or audit_access):
        raise HTTPException(403, "case and audit access denied")


def broad_visibility(user: str) -> bool:
    return bool(
        container.access.decide(user, "manage_access").allowed
        or container.access.decide(user, "view_audit").allowed
    )


def case_broad_visibility(user: str) -> bool:
    return bool(
        broad_visibility(user)
        or container.access.decide(
            user, "manage_selection", stage="07", purpose="case_review"
        ).allowed
    )


def requested_case_owner(user: str, scope: str | None) -> str | None:
    if scope == "all" and case_broad_visibility(user):
        return None
    return requested_owner(user, scope)


def requested_owner(user: str, scope: str | None, owner: str | None = None) -> str | None:
    broad = broad_visibility(user)
    if owner and not broad and owner != user:
        raise HTTPException(403, "cross-user scope requires audit or access-management permission")
    if owner:
        return owner
    if scope == "all":
        if not broad:
            raise HTTPException(403, "all-user scope requires audit or access-management permission")
        return None
    if scope and scope.startswith("user:"):
        selected = scope.split(":", 1)[1]
        if not broad and selected != user:
            raise HTTPException(403, "cross-user scope requires audit or access-management permission")
        return selected
    if scope == "me" or not broad:
        return user
    return None


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(static_root / "standard.html")


@app.get("/advanced", include_in_schema=False)
def advanced_index():
    return FileResponse(static_root / "index.html")


@app.get("/lifecycle", include_in_schema=False)
@app.get("/runs", include_in_schema=False)
@app.get("/runs/{run_id}", include_in_schema=False)
@app.get("/datasets/{dataset_id}/v{version}/{tab}", include_in_schema=False)
@app.get("/cases", include_in_schema=False)
@app.get("/cases/{dataset_id}/v{version}/{step}", include_in_schema=False)
@app.get("/reports", include_in_schema=False)
@app.get("/reports/{case_set_id}/{tab}", include_in_schema=False)
@app.get("/oversight", include_in_schema=False)
@app.get("/oversight/{tab}", include_in_schema=False)
@app.get("/reference", include_in_schema=False)
@app.get("/settings", include_in_schema=False)
@app.get("/settings/{section}", include_in_schema=False)
def standard_ui():
    """Serve browser-history routes for the standard control-plane UI."""
    return FileResponse(static_root / "standard.html")


@app.get("/api/v1/health")
def health():
    identity = container.db.ping()
    return {
        "status": "ok",
        "version": app.version,
        "persistence_backend": "postgresql",
        "database": identity,
        "worker_status": "available",
        "ui_impersonation": os.getenv("CBCR_UI_IMPERSONATION", "0") == "1",
        "source_connectors": {
            "fixture-json": "active",
            "postgresql-canonical": "active",
            "database-api": "extension_boundary",
        },
    }


@app.get("/api/v1/me")
def me(user: Annotated[str, Depends(actor)]):
    value = container.admin.current_user(user)
    if not value or not value["active"]:
        raise HTTPException(403, "active application user not found")
    value["persona"] = (
        "Administrator" if "platform_admin" in value["roles"] else
        "Auditor" if "auditor" in value["roles"] else
        "Case Reviewer" if "case_manager" in value["roles"] else
        "Analyst"
    )
    return value


@app.get("/api/v1/impersonation-users", include_in_schema=False)
def impersonation_users(user: Annotated[str, Depends(actor)]):
    if os.getenv("CBCR_UI_IMPERSONATION", "0") != "1":
        raise HTTPException(404, "UI impersonation is disabled")
    if not container.admin.current_user(user):
        raise HTTPException(403, "active application user not found")
    return container.admin.users()


@app.get("/api/v1/sources")
def sources(user: Annotated[str, Depends(actor)]):
    require(user, "view_sources")
    return container.catalogue.list_sources()


@app.put("/api/v1/sources/{source_id}")
def save_source(
    source_id: str, value: SourceCreate, user: Annotated[str, Depends(actor)]
):
    require(user, "manage_sources")
    if source_id != value.source_id:
        raise HTTPException(400, "path and body source_id must match")
    try:
        container.catalogue.save_source(value)
    except ConflictError as exc:
        raise HTTPException(422, str(exc)) from exc
    container.db.audit(
        new_uuid(), user, "SAVE_SOURCE", f"source:{source_id}", "allowed"
    )
    return {"source_id": source_id}


@app.post("/api/v1/mappings", status_code=201)
def create_mapping(value: MappingProfileCreate, user: Annotated[str, Depends(actor)]):
    require(user, "manage_sources")
    try:
        container.catalogue.save_mapping_draft(value)
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"profile_id": value.profile_id, "version": value.version, "lifecycle": "draft"}


@app.post("/api/v1/mappings/{profile_id}/versions/{version}/activate")
def activate_mapping(
    profile_id: str, version: int, user: Annotated[str, Depends(actor)]
):
    require(user, "manage_sources")
    try:
        container.catalogue.activate_mapping(profile_id, version)
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"lifecycle": "active"}


@app.get("/api/v1/data-dictionary/canonical")
def get_canonical_dictionary(user: Annotated[str, Depends(actor)]):
    require(user, "view_dictionary")
    return canonical_dictionary()


@app.get("/api/v1/mappings/{profile_id}/versions/{version}/dictionary")
def mapping_dictionary(
    profile_id: str, version: int, user: Annotated[str, Depends(actor)]
):
    require(user, "view_dictionary")
    return container.admin.mapping_dictionary(profile_id, version)


@app.put("/api/v1/mappings/{profile_id}/versions/{version}/dictionary")
def save_mapping_dictionary(
    profile_id: str,
    version: int,
    value: MappingDictionaryRequest,
    user: Annotated[str, Depends(actor)],
):
    require(user, "manage_sources")
    try:
        count = container.admin.save_mapping_dictionary(profile_id, version, value)
    except AdminConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"profile_id": profile_id, "version": version, "entry_count": count}


@app.get("/api/v1/mappings/{profile_id}/versions/{version}/validate")
def validate_mapping(
    profile_id: str, version: int, user: Annotated[str, Depends(actor)]
):
    require(user, "view_dictionary")
    try:
        return container.catalogue.mapping_validation(profile_id, version)
    except ConflictError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/v1/pipeline-profiles")
def pipeline_profiles(user: Annotated[str, Depends(actor)]):
    require(user, "view_datasets")
    return container.admin.pipeline_profiles()


@app.put("/api/v1/pipeline-profiles/{profile_id}")
def save_pipeline_profile(
    profile_id: str,
    value: PipelineProfileRequest,
    user: Annotated[str, Depends(actor)],
):
    require(user, "manage_pipeline_profiles")
    if profile_id != value.profile_id:
        raise HTTPException(400, "path and body profile_id must match")
    if value.route[0] != "landing" or value.route[-1] != "risk_ready":
        raise HTTPException(422, "route must start at landing and end at risk_ready")
    canonical_order = ["landing", "canonical", "dq_passed", "enriched", "risk_ready"]
    positions = [canonical_order.index(zone) for zone in value.route]
    if positions != sorted(set(positions)) or "canonical" not in value.route:
        raise HTTPException(422, "route must contain canonical and follow the governed zone order")
    if "dq_passed" not in value.route and "enriched" not in value.route:
        raise HTTPException(
            422, "at least one governed quality/enrichment publication zone is required"
        )
    missing = set(value.route) - set(value.storage_bindings)
    if missing:
        raise HTTPException(
            422, f"storage bindings missing for: {', '.join(sorted(missing))}"
        )
    container.admin.save_pipeline_profile(value)
    return {"profile_id": profile_id, "route": value.route}


@app.post("/api/v1/lots", status_code=201)
def ingest_lot(value: LotIngestRequest, user: Annotated[str, Depends(actor)]):
    require(user, "manage_datasets", purpose="data_quality")
    try:
        result = container.data_plane.ingest(
            value.source_id,
            user,
            value.report_ids,
            value.external_lot_ref,
            value.metadata,
            value.pipeline_profile_id,
        )
    except DataPlaneError as exc:
        raise HTTPException(422, str(exc)) from exc
    container.db.audit(
        new_uuid(), user, "INGEST_LOT", f"lot:{result['lot_id']}", "allowed", "data_quality", result
    )
    return result


@app.get("/api/v1/lots")
def lots(
    user: Annotated[str, Depends(actor)],
    scope: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    source_id: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    require(user, "view_datasets")
    return container.admin.lots(
        owner=requested_owner(user, scope, owner), status=status, source_id=source_id,
        query=q, date_from=date_from, date_to=date_to, page=page, page_size=page_size,
    )


@app.get("/api/v1/datasets")
def datasets(
    user: Annotated[str, Depends(actor)],
    lot_id: str | None = None,
    zone: str | None = None,
    scope: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    require(user, "view_datasets")
    if scope == "case_workbench":
        require_case_view(user)
        if zone != "risk_ready":
            raise HTTPException(422, "case_workbench scope is limited to risk_ready datasets")
        selected_owner = None
    else:
        selected_owner = requested_owner(user, scope, owner)
    return container.data_plane.list_datasets(
        lot_id, zone, owner=selected_owner, status=status,
        query=q, date_from=date_from, date_to=date_to, page=page, page_size=page_size,
    )


@app.get("/api/v1/datasets/{dataset_id}/versions/{version}")
def dataset(dataset_id: str, version: int, user: Annotated[str, Depends(actor)]):
    require(user, "view_datasets")
    value = container.data_plane.dataset(dataset_id, version)
    if not value:
        raise HTTPException(404, "dataset version not found")
    return value


@app.get("/api/v1/datasets/{dataset_id}/versions/{version}/reports")
def dataset_reports(dataset_id: str, version: int, user: Annotated[str, Depends(actor)]):
    require(user, "view_datasets")
    try:
        return [
            report.model_dump(mode="json")
            for report in container.data_plane.canonical_api(dataset_id, version).list_reports()
        ]
    except DataPlaneError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/v1/datasets/{dataset_id}/versions/{version}/lineage")
def dataset_lineage(dataset_id: str, version: int, user: Annotated[str, Depends(actor)]):
    require(user, "view_datasets")
    return container.data_plane.lineage(dataset_id, version)


@app.post("/api/v1/dataset-runs", status_code=202)
def create_dataset_run(value: DatasetRunRequest, user: Annotated[str, Depends(actor)]):
    try:
        run_id = container.runs.create_dataset_run(value, user)
    except AccessDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except (RunValidationError, DataPlaneError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"run_id": run_id, "status": "queued", "status_url": f"/api/v1/runs/{run_id}"}


@app.post(
    "/api/v1/datasets/{dataset_id}/versions/{version}/evaluate-promotion",
    status_code=201,
)
def evaluate_promotion(
    dataset_id: str,
    version: int,
    value: GateEvaluationRequest,
    user: Annotated[str, Depends(actor)],
):
    require(user, "manage_datasets", purpose="data_quality")
    binding = container.admin.run_binding(value.run_id)
    if not binding or (binding["dataset_id"], binding["dataset_version"]) != (
        dataset_id,
        version,
    ):
        raise HTTPException(422, "run is not bound to this dataset version")
    try:
        return container.data_plane.evaluate(value.run_id, value.blocking_severities, user)
    except DataPlaneError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/v1/evaluations/{evaluation_id}/dispositions")
def dispositions(evaluation_id: str, user: Annotated[str, Depends(actor)]):
    require(user, "view_datasets")
    return container.data_plane.dispositions(evaluation_id)


@app.post("/api/v1/datasets/{dataset_id}/versions/{version}/promote", status_code=201)
def promote_dataset(
    dataset_id: str,
    version: int,
    value: PromotionRequest,
    user: Annotated[str, Depends(actor)],
):
    purpose = "risk_assessment" if value.target_zone == "risk_ready" else "data_quality"
    require(user, "manage_datasets", purpose=purpose)
    try:
        return container.data_plane.promote(
            dataset_id,
            version,
            value.target_zone,
            user,
            value.evaluation_id,
            value.enrichment_values,
            value.reason,
        )
    except DataPlaneError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/v1/functions")
def functions(
    user: Annotated[str, Depends(actor)], lifecycle: str | None = Query("active")
):
    require(user, "view_catalogue")
    return container.catalogue.list_functions(lifecycle or None)


@app.post("/api/v1/functions", status_code=201)
def create_function(value: FunctionDraft, user: Annotated[str, Depends(actor)]):
    require(user, "manage_catalogue")
    try:
        version = container.catalogue.save_function_draft(value, user)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    container.db.audit(
        new_uuid(), user, "CREATE_FUNCTION_DRAFT", f"function:{value.code}:{version}", "allowed"
    )
    return {"code": value.code, "version": version, "lifecycle": "draft"}


@app.post("/api/v1/functions/{code}/versions/{version}/activate")
def activate_function(code: str, version: int, user: Annotated[str, Depends(actor)]):
    require(user, "manage_catalogue")
    definition = next(
        (
            row
            for row in container.catalogue.list_functions(None)
            if row["code"] == code and row["version"] == version
        ),
        None,
    )
    if not definition or definition["handler"] not in HANDLERS:
        raise HTTPException(409, "function handler is not installed")
    try:
        container.catalogue.activate_function(code, version)
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    container.db.audit(
        new_uuid(), user, "ACTIVATE_FUNCTION", f"function:{code}:{version}", "allowed"
    )
    return {"code": code, "version": version, "lifecycle": "active"}


@app.post("/api/v1/functions/{code}/versions/{version}/retire")
def retire_function(code: str, version: int, user: Annotated[str, Depends(actor)]):
    require(user, "manage_catalogue")
    container.catalogue.retire_function(code, version)
    container.db.audit(
        new_uuid(), user, "RETIRE_FUNCTION", f"function:{code}:{version}", "allowed"
    )
    return {"lifecycle": "retired"}


@app.delete("/api/v1/functions/{code}/versions/{version}", status_code=204)
def delete_function(code: str, version: int, user: Annotated[str, Depends(actor)]):
    require(user, "manage_catalogue")
    container.catalogue.delete_function_draft(code, version)
    container.db.audit(
        new_uuid(), user, "DELETE_FUNCTION_DRAFT", f"function:{code}:{version}", "allowed"
    )


@app.post("/api/v1/runs", status_code=202)
def create_run(value: RunRequest, user: Annotated[str, Depends(actor)]):
    try:
        run_id = container.runs.create(value, user)
    except AccessDenied as exc:
        raise HTTPException(403, str(exc)) from exc
    except (RunValidationError, DataPlaneError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"run_id": run_id, "status": "queued", "status_url": f"/api/v1/runs/{run_id}"}


@app.get("/api/v1/runs")
def list_runs(
    user: Annotated[str, Depends(actor)],
    scope: str | None = None,
    owner: str | None = None,
    status: str | None = None,
    purpose: str | None = None,
    function_code: str | None = None,
    input_zone: str | None = None,
    dataset_id: str | None = None,
    lot_id: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    visible = []
    for summary in container.runs.list(
        owner=requested_owner(user, scope, owner), status=status, purpose=purpose,
        function_code=function_code, input_zone=input_zone, dataset_id=dataset_id,
        lot_id=lot_id, query=q, date_from=date_from, date_to=date_to,
        page=page, page_size=page_size,
    ):
        value = container.runs.get(summary["run_id"])
        if value and may_view_run(user, value):
            visible.append(summary)
    return visible


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, user: Annotated[str, Depends(actor)]):
    value = container.runs.get(run_id)
    if not value:
        raise HTTPException(404, "run not found")
    require_run_view(user, value)
    return value


@app.get("/api/v1/runs/{run_id}/findings")
def findings(run_id: str, user: Annotated[str, Depends(actor)]):
    value = container.runs.get(run_id)
    if not value:
        raise HTTPException(404, "run not found")
    require_run_view(user, value)
    return container.runs.findings(run_id)


@app.get("/api/v1/risk-results")
def risk_results(
    user: Annotated[str, Depends(actor)],
    dataset_id: str | None = None,
    run_id: str | None = None,
    report_id: str | None = None,
):
    require(user, "view_results", stage="05", purpose="risk_assessment")
    return container.admin.risk_results(dataset_id, run_id, report_id)


@app.get("/api/v1/selection-batches")
def selection_batches(
    user: Annotated[str, Depends(actor)], scope: str | None = None
):
    require(user, "view_results", stage="07", purpose="case_review")
    return container.admin.selection_batches(requested_case_owner(user, scope))


@app.get("/api/v1/datasets/{dataset_id}/versions/{version}/risk-runs")
def completed_risk_runs(
    dataset_id: str, version: int, user: Annotated[str, Depends(actor)]
):
    require(user, "view_datasets")
    return container.risk_result_sets.completed_runs(dataset_id, version)


@app.get("/api/v1/risk-result-sets")
def risk_result_sets(
    user: Annotated[str, Depends(actor)], dataset_id: str | None = None,
    scope: str | None = None,
):
    require_case_view(user)
    return container.risk_result_sets.list(dataset_id, requested_case_owner(user, scope))


@app.post("/api/v1/risk-result-sets", status_code=201)
def create_risk_result_set(
    value: RiskResultSetCreate, user: Annotated[str, Depends(actor)]
):
    require(user, "manage_selection", stage="07", purpose="case_review")
    try:
        return container.risk_result_sets.create(value, user)
    except RiskResultSetError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/v1/risk-result-sets/{result_set_id}")
def get_risk_result_set(
    result_set_id: str, user: Annotated[str, Depends(actor)]
):
    require_case_view(user)
    value = container.risk_result_sets.get(result_set_id)
    if not value:
        raise HTTPException(404, "risk-result set not found")
    return value


@app.post("/api/v1/risk-result-sets/{result_set_id}/approve")
def approve_risk_result_set(
    result_set_id: str,
    value: RiskResultSetApproval,
    user: Annotated[str, Depends(actor)],
):
    require(user, "manage_selection", stage="07", purpose="case_review")
    try:
        return container.risk_result_sets.approve(result_set_id, user, value.rationale)
    except RiskResultSetError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/v1/selection-batches/{batch_id}/candidates")
def selection_candidates(
    batch_id: str,
    user: Annotated[str, Depends(actor)],
    decision: str | None = None,
    min_score: float | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    require(user, "view_results", stage="07", purpose="case_review")
    return container.admin.selection_candidates(
        batch_id, decision=decision, minimum_score=min_score, query=q,
        page=page, page_size=page_size,
    )


@app.post("/api/v1/selection-batches/{batch_id}/finalize", status_code=201)
def finalize_selection_batch(
    batch_id: str,
    value: CaseSetFinalizeRequest,
    user: Annotated[str, Depends(actor)],
):
    require(user, "manage_selection", stage="07", purpose="case_review")
    try:
        return container.case_handoff.finalize(batch_id, value, user)
    except CaseHandoffError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/v1/case-sets")
def case_sets(user: Annotated[str, Depends(actor)], scope: str | None = None):
    require_case_view(user)
    return container.case_handoff.case_sets(requested_case_owner(user, scope))


@app.get("/api/v1/case-sets/{case_set_id}")
def case_set(case_set_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    value = container.case_handoff.case_set(case_set_id)
    if not value:
        raise HTTPException(404, "case set not found")
    return value


@app.get("/api/v1/case-sets/{case_set_id}/export")
def export_case_set(case_set_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    try:
        return container.case_handoff.export_case_set(case_set_id)
    except CaseHandoffError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/v1/case-sets/{case_set_id}/reports/selected-cases")
def selected_cases_report(case_set_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    try:
        return container.reports.selected_cases(case_set_id)
    except CaseReportError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/v1/case-sets/{case_set_id}/reports/selected-cases.csv")
def selected_cases_report_csv(case_set_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    try:
        content = container.reports.selected_cases_csv(case_set_id)
    except CaseReportError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="selected-cases-{case_set_id}.csv"'
        },
    )


@app.get("/api/v1/case-sets/{case_set_id}/reports/selected-cases.pdf")
def selected_cases_report_pdf(case_set_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    try:
        content = container.reports.selected_cases_pdf(case_set_id)
    except CaseReportError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="selected-cases-{case_set_id}.pdf"'
        },
    )


@app.get("/api/v1/case-sets/{case_set_id}/reports/lineage")
def case_set_lineage_report(case_set_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    try:
        return container.reports.lineage(case_set_id)
    except CaseReportError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/v1/case-sets/{case_set_id}/reports/lineage.csv")
def case_set_lineage_report_csv(case_set_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    try:
        content = container.reports.lineage_csv(case_set_id)
    except CaseReportError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="case-lineage-{case_set_id}.csv"'
        },
    )


@app.get("/api/v1/case-sets/{case_set_id}/reports/lineage.pdf")
def case_set_lineage_report_pdf(case_set_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    try:
        content = container.reports.lineage_pdf(case_set_id)
    except CaseReportError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="case-lineage-{case_set_id}.pdf"'
        },
    )


@app.get("/api/v1/audit-cases")
def audit_cases(
    user: Annotated[str, Depends(actor)],
    case_set_id: str | None = None,
    status: str | None = None,
):
    require_case_view(user)
    return container.case_handoff.audit_cases(case_set_id=case_set_id, status=status)


@app.get("/api/v1/audit-cases/{audit_case_id}")
def audit_case(audit_case_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    value = container.case_handoff.audit_case(audit_case_id)
    if not value:
        raise HTTPException(404, "audit case not found")
    return value


@app.put("/api/v1/audit-cases/{audit_case_id}/status")
def update_audit_case(
    audit_case_id: str,
    value: AuditCaseStatusRequest,
    user: Annotated[str, Depends(actor)],
):
    require(user, "manage_selection", stage="07", purpose="case_review")
    try:
        return container.case_handoff.update_case(audit_case_id, value, user)
    except CaseHandoffError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/v1/audit-cases/{audit_case_id}/lineage")
def audit_case_lineage(audit_case_id: str, user: Annotated[str, Depends(actor)]):
    require_case_view(user)
    value = container.lineage.audit_case(audit_case_id)
    if not value:
        raise HTTPException(404, "audit case not found")
    return value


@app.put("/api/v1/selection-candidates/{candidate_id}/decision")
def decide_candidate(
    candidate_id: str,
    value: SelectionDecisionRequest,
    user: Annotated[str, Depends(actor)],
):
    require(user, "manage_selection", stage="07", purpose="case_review")
    try:
        return container.admin.decide_candidate(candidate_id, value, user)
    except AdminNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/v1/users")
def users(user: Annotated[str, Depends(actor)]):
    require(user, "manage_access")
    return container.admin.users()


@app.get("/api/v1/roles")
def roles(user: Annotated[str, Depends(actor)]):
    require(user, "manage_access")
    return container.admin.roles()


@app.post("/api/v1/users", status_code=201)
def create_user(value: UserCreate, user: Annotated[str, Depends(actor)]):
    require(user, "manage_access")
    container.admin.create_user(value, user)
    return {"user_id": value.user_id}


@app.put("/api/v1/users/{user_id}/roles")
def assign_roles(
    user_id: str, value: RoleAssignment, user: Annotated[str, Depends(actor)]
):
    require(user, "manage_access")
    try:
        count = container.admin.assign_roles(user_id, value, user)
    except AdminConflict as exc:
        raise HTTPException(422, str(exc)) from exc
    except AdminNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"user_id": user_id, "role_count": count}


@app.put("/api/v1/users/{user_id}/status")
def set_user_status(
    user_id: str, value: UserStatusRequest, user: Annotated[str, Depends(actor)]
):
    require(user, "manage_access")
    if user_id == user and not value.active:
        raise HTTPException(422, "the current user cannot deactivate itself")
    try:
        container.admin.set_user_active(user_id, value.active, user)
    except AdminNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"user_id": user_id, "active": value.active}


@app.get("/api/v1/audit")
def audit(
    user: Annotated[str, Depends(actor)],
    limit: int = Query(100, ge=1, le=1000),
    actor_id: str | None = Query(None, alias="actor"),
    role: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    target: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
):
    require(user, "view_audit")
    return container.admin.audit(
        limit, actor=actor_id, role=role, action=action, decision=outcome,
        target=target, date_from=date_from, date_to=date_to, page=page,
    )


@app.get("/api/v1/lookup")
def lookup(value: str, user: Annotated[str, Depends(actor)]):
    require(user, "view_datasets")
    result = container.admin.lookup(value.strip())
    if not result:
        raise HTTPException(404, "identifier or reference not found")
    return result


@app.get("/api/v1/dashboard")
def dashboard(
    user: Annotated[str, Depends(actor)],
    scope: str | None = None,
    days: int = Query(30, ge=1, le=366),
):
    require(user, "view_datasets")
    owner = requested_owner(user, scope)
    date_from = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    runs = container.runs.list(owner=owner, date_from=date_from, page_size=500)
    workflow_runs = container.runs.list(owner=owner, page_size=500)
    datasets = container.data_plane.list_datasets(owner=owner, page_size=500)
    active = [run for run in runs if run["status"] in {"queued", "running"}]
    failed = [run for run in runs if run["status"] in {"failed", "completed_with_errors"}]
    parent_keys = {
        (item.get("parent_dataset_id"), item.get("parent_version"))
        for item in datasets if item.get("parent_dataset_id")
    }
    latest = [
        item for item in datasets
        if (item["dataset_id"], item["version"]) not in parent_keys
    ]
    completed_dq = {
        (run["dataset_id"], run["dataset_version"])
        for run in workflow_runs
        if run["purpose"] == "data_quality"
        and run["status"] in {"completed", "completed_with_errors"}
    }
    awaiting_dq_run = [
        item for item in latest if item["zone"] == "canonical"
        and (item["dataset_id"], item["version"]) not in completed_dq
    ]
    awaiting_dq_gate = [
        item for item in latest if item["zone"] == "canonical"
        and (item["dataset_id"], item["version"]) in completed_dq
    ]
    approved_evidence = {
        (str(row["dataset_id"]), row["dataset_version"])
        for row in container.db.all(
            "SELECT dataset_id,dataset_version FROM cbcr_risk.result_set WHERE status='approved'"
        )
    }
    cards = {
        "failed_runs": len(failed),
        "active_runs": len(active),
        "awaiting_dq_run": len(awaiting_dq_run),
        "awaiting_dq_gate": len(awaiting_dq_gate),
        "awaiting_publication": sum(1 for item in latest if item["zone"] in {"dq_passed", "enriched"}),
        "risk_ready": sum(1 for item in latest if item["zone"] == "risk_ready"),
        "awaiting_evidence_approval": sum(
            1 for item in latest if item["zone"] == "risk_ready"
            and (item["dataset_id"], item["version"]) not in approved_evidence
        ),
        "pending_case_decisions": 0,
    }
    if container.access.decide(user, "view_results", stage="07", purpose="case_review").allowed:
        where = "WHERE c.decision='pending' AND b.status='open'"
        params: tuple[object, ...] = ()
        if owner:
            where += " AND l.received_by=%s"
            params = (owner,)
        cards["pending_case_decisions"] = int(
            container.db.one(
                f"""SELECT COUNT(*) AS count
                    FROM cbcr_selection.candidate c
                    JOIN cbcr_selection.selection_batch b ON b.selection_batch_id=c.selection_batch_id
                    JOIN cbcr_control.dataset d
                      ON d.dataset_id=b.dataset_id AND d.version=b.dataset_version
                    JOIN cbcr_control.lot l ON l.lot_id=d.lot_id
                    {where}""",
                params,
            )["count"]
        )
    by_zone = {zone: sum(1 for item in datasets if item["zone"] == zone) for zone in (
        "landing", "canonical", "dq_passed", "enriched", "risk_ready"
    )}
    by_status = {status: sum(1 for item in runs if item["status"] == status) for status in (
        "queued", "running", "completed", "completed_with_errors", "failed"
    )}
    return {
        "period_days": days,
        "scope": scope or ("all" if owner is None else "me"),
        "cards": cards,
        "lots_by_zone": by_zone,
        "runs_by_status": by_status,
        "recent_runs": runs[:6],
    }
