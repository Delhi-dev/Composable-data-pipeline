from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


StageCode = Literal["01", "02", "03", "04", "05", "06", "07"]
DataZone = Literal["landing", "canonical", "dq_passed", "enriched", "risk_ready"]


class CanonicalEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    name: str
    tax_jurisdiction: str
    tin: str | None = None
    role: str | None = None


class CanonicalMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jurisdiction: str
    currency_code: str | None = None
    currency_by_measure: dict[str, str] = Field(default_factory=dict)
    revenue: Decimal | None = None
    profit_before_tax: Decimal | None = None
    income_tax_paid: Decimal | None = None
    income_tax_accrued: Decimal | None = None
    employees: int | None = None
    tangible_assets: Decimal | None = None
    stated_capital: Decimal | None = None
    accumulated_earnings: Decimal | None = None
    unrelated_revenue: Decimal | None = None
    related_revenue: Decimal | None = None

    @field_validator("jurisdiction")
    @classmethod
    def uppercase_jurisdiction(cls, value: str) -> str:
        return value.upper()


class CanonicalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    message_ref_id: str
    reporting_entity_id: str
    reporting_entity_name: str
    reporting_period_end: date
    reporting_currency: str | None = None
    receiving_jurisdiction: str
    entities: list[CanonicalEntity] = Field(default_factory=list)
    metrics: list[CanonicalMetric] = Field(default_factory=list)

    @field_validator("reporting_currency", "receiving_jurisdiction")
    @classmethod
    def uppercase_codes(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class Finding(BaseModel):
    function_code: str
    report_id: str | None = None
    entity_id: str | None = None
    jurisdiction: str | None = None
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class FunctionResult(BaseModel):
    status: Literal["succeeded", "failed"] = "succeeded"
    summary: dict[str, Any] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class SourceCreate(BaseModel):
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    name: str
    adapter_type: Literal["fixture-json", "postgresql-canonical", "database-api"]
    endpoint_link: str
    secret_ref: str | None = None


class MappingProfileCreate(BaseModel):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    source_id: str
    version: int = Field(ge=1)
    mapping: dict[str, Any]


class RunRequest(BaseModel):
    source_id: str
    report_ids: list[str] | None = None
    functions: list[str] = Field(min_length=1)
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    purpose: Literal["data_quality", "risk_assessment", "case_review"]


class FunctionDraft(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    stage: StageCode
    name: str
    description: str
    handler: str
    purpose: str
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    output_classification: Literal["internal", "restricted", "highly_restricted"] = "restricted"


class UserCreate(BaseModel):
    user_id: str
    display_name: str


class RoleAssignment(BaseModel):
    role_ids: list[str]


class LotIngestRequest(BaseModel):
    source_id: str
    pipeline_profile_id: str = "ideal_separated"
    report_ids: list[str] | None = None
    external_lot_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetRunRequest(BaseModel):
    dataset_id: str
    dataset_version: int = Field(default=1, ge=1)
    input_zone: DataZone
    report_ids: list[str] | None = None
    functions: list[str] = Field(min_length=1)
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    purpose: Literal["data_quality", "risk_assessment", "case_review"]


class GateEvaluationRequest(BaseModel):
    run_id: str
    blocking_severities: list[Literal["warning", "error"]] = Field(default_factory=lambda: ["error"])


class EnrichmentValue(BaseModel):
    report_id: str
    entity_id: str | None = None
    attribute_name: str
    value: Any
    source_ref: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class PromotionRequest(BaseModel):
    target_zone: DataZone
    evaluation_id: str | None = None
    enrichment_values: list[EnrichmentValue] = Field(default_factory=list)
    reason: str | None = None


class SelectionDecisionRequest(BaseModel):
    decision: Literal["selected", "not_selected", "deferred"]
    rationale: str = Field(min_length=1)


class ColumnDictionaryEntry(BaseModel):
    logical_object: Literal["report", "entity", "metric"]
    canonical_field: str
    physical_schema: str | None = None
    physical_table: str | None = None
    physical_column: str
    data_type: str | None = None
    nullable: bool = True
    description: str | None = None
    transform: dict[str, Any] = Field(default_factory=dict)


class MappingDictionaryRequest(BaseModel):
    entries: list[ColumnDictionaryEntry]


class PipelineProfileRequest(BaseModel):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    name: str
    route: list[DataZone] = Field(min_length=2)
    storage_bindings: dict[DataZone, str]
