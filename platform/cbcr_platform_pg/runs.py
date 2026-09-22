from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from cbcr_platform.contracts import DatasetRunRequest, FunctionResult, RunRequest
from cbcr_platform.function_library import HANDLERS

from .access import AccessService
from .data_plane import DataPlaneService
from .domestic import DomesticRiskRepository
from cbcr_platform.canonical import CanonicalDataAPI
from .database import PostgreSQLDatabase, PostgreSQLSession, new_uuid, utc_now


class RunValidationError(ValueError):
    pass


def _parameter_values(schema: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    unknown = set(supplied) - set(schema)
    if unknown:
        raise RunValidationError(f"unknown parameters: {', '.join(sorted(unknown))}")
    values = {key: item["default"] for key, item in schema.items() if "default" in item}
    values.update(supplied)
    for key, value in values.items():
        expected = schema[key].get("type")
        valid = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "array": isinstance(value, list),
        }.get(expected, True)
        if not valid:
            raise RunValidationError(f"parameter {key} must be {expected}")
    return values


def _stable_key(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _string_ids(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        if row.get(key) is not None:
            row[key] = str(row[key])
    return row


class RunService:
    def __init__(
        self,
        db: PostgreSQLDatabase,
        access: AccessService,
        data_plane: DataPlaneService,
        *,
        maximum_attempts: int = 3,
        lease_seconds: int = 60,
    ):
        self.db = db
        self.access = access
        self.data_plane = data_plane
        self.maximum_attempts = maximum_attempts
        self.lease_seconds = lease_seconds

    def _definitions(
        self,
        functions: list[str],
        parameters: dict[str, dict[str, Any]],
        purpose: str,
        actor: str,
        input_zone: str | None = None,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        definitions = []
        for code in functions:
            row = self.db.one(
                """SELECT function_code AS code,version,stage,name,description,handler,purpose,
                          parameter_schema,output_classification,lifecycle
                   FROM cbcr_control.function_definition
                   WHERE function_code=%s AND lifecycle='active'""",
                (code,),
            )
            if not row:
                raise RunValidationError(f"active function not found: {code}")
            if row["purpose"] != purpose:
                raise RunValidationError(f"{code} requires purpose {row['purpose']}")
            if input_zone:
                allowed = {
                    "landing": {"01"},
                    "canonical": {"01", "02", "03", "04"},
                    "dq_passed": {"03", "04"},
                    "enriched": {"03", "04"},
                    "risk_ready": {"05", "06", "07"},
                }[input_zone]
                if row["stage"] not in allowed:
                    raise RunValidationError(
                        f"stage {row['stage']} cannot consume {input_zone} data"
                    )
                if purpose in {"risk_assessment", "case_review"} and input_zone != "risk_ready":
                    raise RunValidationError("risk and selection functions require a risk_ready dataset")
            self.access.require(actor, "run_function", stage=row["stage"], purpose=purpose)
            values = _parameter_values(row["parameter_schema"], parameters.get(code, {}))
            definitions.append((row, values))
        extras = set(parameters) - set(functions)
        if extras:
            raise RunValidationError("parameters supplied for unselected functions")
        return definitions

    def create(self, request: RunRequest, actor: str) -> str:
        source = self.db.one(
            "SELECT source_id FROM cbcr_control.source WHERE source_id=%s AND enabled=true",
            (request.source_id,),
        )
        if not source:
            raise RunValidationError("enabled source not found")
        # Compatibility endpoint: source-bound DQ runs start at canonical, while
        # risk/case runs explicitly use the trusted-source route and are advanced
        # to their contractually valid input zone before the run is queued.
        input_zone = "canonical" if request.purpose == "data_quality" else "risk_ready"
        profile_id = "ideal_separated" if input_zone == "canonical" else "trusted_prevalidated"
        # Validate before implicit intake so invalid requests do not create datasets.
        self._definitions(
            request.functions, request.parameters, request.purpose, actor, input_zone
        )
        intake = self.data_plane.ingest(
            request.source_id,
            actor,
            request.report_ids,
            external_lot_ref=f"implicit-run-{new_uuid()}",
            metadata={"implicit_intake": True, "purpose": request.purpose},
            pipeline_profile_id=profile_id,
        )
        dataset_id = intake["canonical_dataset"]["dataset_id"]
        if input_zone == "risk_ready":
            enriched = self.data_plane.promote(
                dataset_id,
                1,
                "enriched",
                actor,
                reason="implicit trusted-source compatibility route",
            )
            risk_ready = self.data_plane.promote(
                enriched["target_dataset_id"],
                enriched["target_version"],
                "risk_ready",
                actor,
                reason="implicit trusted-source compatibility route",
            )
            dataset_id = risk_ready["target_dataset_id"]
        run_id = self.create_dataset_run(
            DatasetRunRequest(
                dataset_id=dataset_id,
                dataset_version=1,
                input_zone=input_zone,
                report_ids=request.report_ids,
                functions=request.functions,
                parameters=request.parameters,
                purpose=request.purpose,
            ),
            actor,
        )
        self.db.audit(
            new_uuid(),
            actor,
            "IMPLICIT_INTAKE_FOR_RUN",
            f"run:{run_id}",
            "allowed",
            request.purpose,
            {"lot_id": intake["lot_id"], "source_id": request.source_id},
        )
        return run_id

    def create_dataset_run(self, request: DatasetRunRequest, actor: str) -> str:
        dataset = self.data_plane.dataset(request.dataset_id, request.dataset_version)
        if not dataset or dataset["status"] != "published":
            raise RunValidationError("published dataset version not found")
        if dataset["zone"] != request.input_zone:
            raise RunValidationError(
                f"dataset zone is {dataset['zone']}, not {request.input_zone}"
            )
        definitions = self._definitions(
            request.functions,
            request.parameters,
            request.purpose,
            actor,
            request.input_zone,
        )
        run_id, now = new_uuid(), utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO cbcr_control.run
                   (run_id,dataset_id,dataset_version,input_zone,requested_by,purpose,status,
                    selected_functions,parameters,created_at,started_at,completed_at,report_ids)
                   VALUES(%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,NULL,NULL,%s)""",
                (
                    run_id,
                    request.dataset_id,
                    request.dataset_version,
                    request.input_zone,
                    actor,
                    request.purpose,
                    request.functions,
                    request.parameters,
                    now,
                    request.report_ids,
                ),
            )
            for definition, resolved in definitions:
                tx.execute(
                    """INSERT INTO cbcr_control.function_run
                       (function_run_id,run_id,function_code,function_version,stage,status,
                        parameters,attempt,queued_at,started_at,completed_at,result_summary,
                        error,artifacts,maximum_attempts)
                       VALUES(%s,%s,%s,%s,%s,'queued',%s,0,%s,NULL,NULL,NULL,NULL,'[]'::jsonb,%s)""",
                    (
                        new_uuid(),
                        run_id,
                        definition["code"],
                        definition["version"],
                        definition["stage"],
                        resolved,
                        now,
                        self.maximum_attempts,
                    ),
                )
            self.db.audit(
                new_uuid(),
                actor,
                "CREATE_DATASET_RUN",
                f"run:{run_id}",
                "allowed",
                request.purpose,
                {
                    "dataset_id": request.dataset_id,
                    "dataset_version": request.dataset_version,
                    "input_zone": request.input_zone,
                    "functions": request.functions,
                },
                session=tx,
            )
        return run_id

    def get(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            """SELECT r.*,l.source_id,l.mapping_profile_id,l.mapping_version
               FROM cbcr_control.run r
               JOIN cbcr_control.dataset d
                 ON d.dataset_id=r.dataset_id AND d.version=r.dataset_version
               JOIN cbcr_control.lot l ON l.lot_id=d.lot_id
               WHERE r.run_id=%s""",
            (run_id,),
        )
        if not row:
            return None
        _string_ids(row, ("run_id", "dataset_id"))
        children = self.db.all(
            """SELECT function_run_id,run_id,function_code,function_version,stage,status,
                      parameters,attempt AS attempts,queued_at AS created_at,started_at,
                      completed_at,error,result_summary AS summary,artifacts,claimed_by,
                      lease_expires_at,next_attempt_at,maximum_attempts
               FROM cbcr_control.function_run WHERE run_id=%s
               ORDER BY stage,function_code""",
            (run_id,),
        )
        for child in children:
            _string_ids(child, ("function_run_id", "run_id"))
        row["function_runs"] = children
        return row

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT r.run_id,l.source_id,r.requested_by,r.purpose,r.status,
                      r.created_at,r.completed_at
               FROM cbcr_control.run r
               JOIN cbcr_control.dataset d
                 ON d.dataset_id=r.dataset_id AND d.version=r.dataset_version
               JOIN cbcr_control.lot l ON l.lot_id=d.lot_id
               ORDER BY r.created_at DESC"""
        )
        return [_string_ids(row, ("run_id",)) for row in rows]

    def findings(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT finding_id,function_run_id,run_id,function_code,report_id,entity_id,
                      jurisdiction,severity,code,message,evidence,created_at
               FROM cbcr_dq.finding WHERE run_id=%s ORDER BY created_at,finding_id""",
            (run_id,),
        )
        return [
            _string_ids(row, ("finding_id", "function_run_id", "run_id")) for row in rows
        ]

    def canonical_api_for_run(self, run: dict[str, Any]):
        return self.data_plane.canonical_api(
            str(run["dataset_id"]),
            run["dataset_version"],
            run["input_zone"],
            run.get("report_ids"),
        )

    def claim_next(self, worker_id: str) -> dict[str, Any] | None:
        with self.db.transaction() as tx:
            claimed = tx.one(
                """WITH candidate AS (
                       SELECT function_run_id
                       FROM cbcr_control.function_run
                       WHERE status='queued'
                         AND attempt < maximum_attempts
                         AND (next_attempt_at IS NULL OR next_attempt_at<=clock_timestamp())
                       ORDER BY queued_at,stage,function_code
                       FOR UPDATE SKIP LOCKED LIMIT 1
                   )
                   UPDATE cbcr_control.function_run fr
                   SET status='running',attempt=attempt+1,claimed_by=%s,
                       started_at=COALESCE(started_at,clock_timestamp()),
                       lease_expires_at=clock_timestamp()+(%s * interval '1 second')
                   FROM candidate WHERE fr.function_run_id=candidate.function_run_id
                   RETURNING fr.*""",
                (worker_id, self.lease_seconds),
            )
            if not claimed:
                return None
            tx.execute(
                """UPDATE cbcr_control.run SET status='running',
                       started_at=COALESCE(started_at,clock_timestamp())
                   WHERE run_id=%s AND status='queued'""",
                (claimed["run_id"],),
            )
        return self.db.one(
            """SELECT fr.*,fd.handler,r.dataset_id,r.dataset_version,r.input_zone,
                      r.report_ids,r.requested_by,r.purpose
               FROM cbcr_control.function_run fr
               JOIN cbcr_control.function_definition fd
                 ON fd.function_code=fr.function_code AND fd.version=fr.function_version
               JOIN cbcr_control.run r ON r.run_id=fr.run_id
               WHERE fr.function_run_id=%s""",
            (claimed["function_run_id"],),
        )

    def recover_expired(self) -> int:
        with self.db.transaction() as tx:
            rows = tx.all(
                """UPDATE cbcr_control.function_run
                   SET status=CASE WHEN attempt>=maximum_attempts THEN 'failed' ELSE 'queued' END,
                       error=CASE WHEN attempt>=maximum_attempts
                                  THEN jsonb_build_object('message','worker lease expired')
                                  ELSE error END,
                       completed_at=CASE WHEN attempt>=maximum_attempts
                                         THEN clock_timestamp() ELSE NULL END,
                       claimed_by=NULL,lease_expires_at=NULL,
                       next_attempt_at=CASE WHEN attempt>=maximum_attempts
                                            THEN NULL ELSE clock_timestamp() END
                   WHERE status='running' AND lease_expires_at<clock_timestamp()
                   RETURNING run_id"""
            )
            run_ids = {str(row["run_id"]) for row in rows}
            for run_id in run_ids:
                self._finalize_parent(tx, run_id)
            return len(rows)

    def process_claimed(self, claimed: dict[str, Any]) -> None:
        handler = HANDLERS.get(claimed["handler"])
        if not handler:
            self.fail_claimed(claimed, "configured handler is not installed", retryable=False)
            return
        try:
            api = self.canonical_api_for_run(claimed)
            parameters = dict(claimed["parameters"] or {})
            fiscal_year = int(parameters.get("fiscal_year", api.list_reports()[0].reporting_period_end.year))
            if claimed["function_code"] == "load_domestic_risk_context":
                screen_run = parameters.get("screening_run_id")
                if not screen_run:
                    raise ValueError("screening_run_id from a completed analyze_profit_presence_mismatch run is required")
                rows = self.db.all("SELECT DISTINCT report_id FROM cbcr_dq.finding WHERE run_id=%s AND function_code='analyze_profit_presence_mismatch'", (screen_run,))
                report_ids = {row["report_id"] for row in rows if row["report_id"]}
                screened = CanonicalDataAPI([r for r in api.list_reports() if r.report_id in report_ids])
                context = DomesticRiskRepository(self.db).reduce(screened.list_reports(), fiscal_year, float(parameters.get("match_confidence_floor", .85)))
                parameters.update({"__domestic": context, "__screened_report_ids": sorted(report_ids), "fiscal_year": fiscal_year})
            elif claimed["function_code"] in {"analyze_outbound_low_substance_payments", "analyze_interest_stripping"}:
                context_id = parameters.get("domestic_context_id")
                cached = self.db.one("SELECT payload FROM cbcr_risk.domestic_risk_context WHERE context_id=%s AND dataset_id=%s AND dataset_version=%s", (context_id, claimed["dataset_id"], claimed["dataset_version"])) if context_id else None
                parameters["__domestic"] = cached["payload"] if cached else DomesticRiskRepository(self.db).reduce(api.list_reports(), int(parameters.get("fiscal_year", api.list_reports()[0].reporting_period_end.year)), float(parameters.get("match_confidence_floor", .85)))
                parameters["fiscal_year"] = fiscal_year
            result = handler(api, parameters)
            if claimed["function_code"] == "load_domestic_risk_context":
                context_id = new_uuid()
                payload = DomesticRiskRepository.json_ready(parameters["__domestic"])
                self.db.execute(
                    """INSERT INTO cbcr_risk.domestic_risk_context
                       (context_id,dataset_id,dataset_version,screening_run_id,fiscal_year,report_ids,payload)
                       VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                    (context_id, claimed["dataset_id"], claimed["dataset_version"], parameters["screening_run_id"],
                     fiscal_year, parameters["__screened_report_ids"], payload),
                )
                result.artifacts[0].pop("payload", None)
                result.artifacts[0]["domestic_context_id"] = context_id
            self.complete_claimed(claimed, result)
        except Exception as exc:
            self.fail_claimed(claimed, str(exc), retryable=False)

    def complete_claimed(self, claimed: dict[str, Any], result: FunctionResult) -> None:
        run_id = str(claimed["run_id"])
        child_id = str(claimed["function_run_id"])
        with self.db.transaction() as tx:
            tx.execute(
                """UPDATE cbcr_control.function_run
                   SET status=%s,completed_at=%s,result_summary=%s,artifacts=%s,
                       error=NULL,claimed_by=NULL,lease_expires_at=NULL,next_attempt_at=NULL
                   WHERE function_run_id=%s AND status='running'""",
                (
                    result.status,
                    utc_now(),
                    result.summary,
                    result.artifacts,
                    child_id,
                ),
            )
            for finding in result.findings:
                value = finding.model_dump(mode="json")
                dedup_key = _stable_key(value)
                tx.execute(
                    """INSERT INTO cbcr_dq.finding
                       (finding_id,run_id,function_code,report_id,entity_id,jurisdiction,
                        severity,code,message,evidence,created_at,function_run_id,dedup_key)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (
                        new_uuid(),
                        run_id,
                        claimed["function_code"],
                        value["report_id"],
                        value["entity_id"],
                        value["jurisdiction"],
                        value["severity"],
                        value["code"],
                        value["message"],
                        value["evidence"],
                        utc_now(),
                        child_id,
                        dedup_key,
                    ),
                )
            self._persist_business_outputs(tx, claimed, result)
            self._finalize_parent(tx, run_id)

    def fail_claimed(self, claimed: dict[str, Any], message: str, retryable: bool) -> None:
        child_id, run_id = str(claimed["function_run_id"]), str(claimed["run_id"])
        with self.db.transaction() as tx:
            current = tx.one(
                """SELECT attempt,maximum_attempts FROM cbcr_control.function_run
                   WHERE function_run_id=%s FOR UPDATE""",
                (child_id,),
            )
            retry = bool(
                retryable and current and current["attempt"] < current["maximum_attempts"]
            )
            tx.execute(
                """UPDATE cbcr_control.function_run
                   SET status=%s,error=%s,completed_at=%s,claimed_by=NULL,
                       lease_expires_at=NULL,next_attempt_at=%s
                   WHERE function_run_id=%s""",
                (
                    "queued" if retry else "failed",
                    {"message": message[:2000], "retryable": retryable},
                    None if retry else utc_now(),
                    utc_now() + timedelta(seconds=1) if retry else None,
                    child_id,
                ),
            )
            self._finalize_parent(tx, run_id)

    def _persist_business_outputs(
        self, tx: PostgreSQLSession, claimed: dict[str, Any], result: FunctionResult
    ) -> None:
        run_id = str(claimed["run_id"])
        child_id = str(claimed["function_run_id"])
        dataset_id = str(claimed["dataset_id"])
        version = claimed["dataset_version"]
        now = utc_now()
        if claimed["stage"] in {"05", "06"}:
            outputs: list[tuple[str, dict[str, Any], str | None, str | None, str | None, str | None]] = []
            for finding in result.findings:
                value = finding.model_dump(mode="json")
                outputs.append(
                    (
                        f"finding:{_stable_key(value)}",
                        value,
                        finding.report_id,
                        finding.entity_id,
                        finding.jurisdiction,
                        finding.severity,
                    )
                )
            for index, artifact in enumerate(result.artifacts):
                outputs.append(
                    (
                        f"artifact:{index}:{_stable_key(artifact)}",
                        artifact,
                        artifact.get("report_id"),
                        artifact.get("entity_id"),
                        artifact.get("jurisdiction"),
                        None,
                    )
                )
            for output_key, payload, report_id, entity_id, jurisdiction, severity in outputs:
                result_id = new_uuid()
                inserted = tx.one(
                    """INSERT INTO cbcr_risk.result
                       (risk_result_id,run_id,dataset_id,dataset_version,report_id,entity_id,
                        jurisdiction,rule_code,severity,result,created_at,function_run_id,output_key)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING
                       RETURNING risk_result_id""",
                    (
                        result_id,
                        run_id,
                        dataset_id,
                        version,
                        report_id,
                        entity_id,
                        jurisdiction,
                        claimed["function_code"],
                        severity,
                        payload,
                        now,
                        child_id,
                        output_key,
                    ),
                )
                if inserted and payload.get("type") == "risk_component_score":
                    tx.execute(
                        """INSERT INTO cbcr_risk.score_component
                           (component_id,risk_result_id,component_code,score,weight,explanation)
                           VALUES(%s,%s,%s,%s,NULL,%s)""",
                        (
                            new_uuid(),
                            result_id,
                            claimed["function_code"],
                            float(payload.get("score", 0)),
                            f"{payload.get('component_count', 0)} components fired",
                        ),
                    )
        if claimed["stage"] == "07":
            batch = tx.one(
                """INSERT INTO cbcr_selection.selection_batch
                   (selection_batch_id,run_id,dataset_id,dataset_version,status,created_by,created_at)
                   VALUES(%s,%s,%s,%s,'open',%s,%s)
                   ON CONFLICT(run_id) DO UPDATE SET run_id=excluded.run_id
                   RETURNING selection_batch_id""",
                (
                    new_uuid(),
                    run_id,
                    dataset_id,
                    version,
                    claimed["requested_by"],
                    now,
                ),
            )
            batch_id = str(batch["selection_batch_id"])
            api = self.data_plane.canonical_api(dataset_id, version)
            for artifact in result.artifacts:
                if artifact.get("type") != "case_candidate":
                    continue
                report = api.get_report(artifact["report_id"])
                tx.execute(
                    """INSERT INTO cbcr_selection.candidate
                       (candidate_id,selection_batch_id,report_id,entity_id,entity_name,
                        reason_code,score,evidence,decision,decision_rationale,decided_by,decided_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'pending',NULL,NULL,NULL)
                       ON CONFLICT DO NOTHING""",
                    (
                        new_uuid(),
                        batch_id,
                        artifact["report_id"],
                        artifact.get("entity_id"),
                        report.reporting_entity_name if report else None,
                        artifact.get("reason_code", claimed["function_code"]),
                        artifact.get("score") or artifact.get("maximum_margin"),
                        artifact,
                    ),
                )

    def _finalize_parent(self, tx: PostgreSQLSession, run_id: str) -> None:
        counts = tx.one(
            """SELECT COUNT(*) FILTER(WHERE status IN ('queued','running')) AS remaining,
                      COUNT(*) FILTER(WHERE status='failed') AS failed
               FROM cbcr_control.function_run WHERE run_id=%s""",
            (run_id,),
        )
        if counts and counts["remaining"] == 0:
            tx.execute(
                """UPDATE cbcr_control.run SET status=%s,completed_at=%s
                   WHERE run_id=%s AND status IN ('queued','running')""",
                (
                    "completed_with_errors" if counts["failed"] else "completed",
                    utc_now(),
                    run_id,
                ),
            )
