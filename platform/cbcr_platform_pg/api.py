from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cbcr_platform.contracts import (
    DatasetRunRequest,
    FunctionDraft,
    GateEvaluationRequest,
    LotIngestRequest,
    MappingDictionaryRequest,
    MappingProfileCreate,
    PipelineProfileRequest,
    PromotionRequest,
    RoleAssignment,
    RunRequest,
    SelectionDecisionRequest,
    SourceCreate,
    UserCreate,
)
from cbcr_platform.dictionary import canonical_dictionary
from cbcr_platform.function_library import HANDLERS

from .access import AccessDenied
from .admin import AdminConflict, AdminNotFound
from .catalog import ConflictError
from .container import PostgreSQLContainer
from .data_plane import DataPlaneError
from .database import new_uuid, utc_now
from .runs import RunValidationError


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


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(static_root / "index.html")


@app.get("/api/v1/health")
def health():
    identity = container.db.ping()
    return {
        "status": "ok",
        "version": app.version,
        "persistence_backend": "postgresql",
        "database": identity,
        "source_connectors": {
            "fixture-json": "active",
            "postgresql-canonical": "active",
            "database-api": "extension_boundary",
        },
    }


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
def lots(user: Annotated[str, Depends(actor)]):
    require(user, "view_datasets")
    return container.admin.lots()


@app.get("/api/v1/datasets")
def datasets(
    user: Annotated[str, Depends(actor)],
    lot_id: str | None = None,
    zone: str | None = None,
):
    require(user, "view_datasets")
    return container.data_plane.list_datasets(lot_id, zone)


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
def list_runs(user: Annotated[str, Depends(actor)]):
    visible = []
    for summary in container.runs.list():
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
def selection_batches(user: Annotated[str, Depends(actor)]):
    require(user, "view_results", stage="07", purpose="case_review")
    return container.admin.selection_batches()


@app.get("/api/v1/selection-batches/{batch_id}/candidates")
def selection_candidates(batch_id: str, user: Annotated[str, Depends(actor)]):
    require(user, "view_results", stage="07", purpose="case_review")
    return container.admin.selection_candidates(batch_id)


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


@app.get("/api/v1/audit")
def audit(
    user: Annotated[str, Depends(actor)], limit: int = Query(100, ge=1, le=1000)
):
    require(user, "view_audit")
    return container.admin.audit(limit)
