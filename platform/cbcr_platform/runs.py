from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from .access import AccessService
from .canonical import CanonicalDataAPI, CanonicalMapper, SourceGateway, snapshot_hash
from .contracts import DatasetRunRequest, RunRequest
from .data_plane import DataPlaneService
from .database import Database, utc_now
from .function_library import HANDLERS


class RunValidationError(ValueError):
    pass


def _id() -> str:
    return str(uuid.uuid4())


def _parameter_values(schema: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    unknown = set(supplied) - set(schema)
    if unknown:
        raise RunValidationError(f"unknown parameters: {', '.join(sorted(unknown))}")
    values = {key: item["default"] for key, item in schema.items() if "default" in item}
    values.update(supplied)
    for key, value in values.items():
        expected = schema[key].get("type")
        valid = {
            "string": isinstance(value, str), "number": isinstance(value, (int, float)),
            "integer": isinstance(value, int), "boolean": isinstance(value, bool),
            "array": isinstance(value, list),
        }.get(expected, True)
        if not valid:
            raise RunValidationError(f"parameter {key} must be {expected}")
    return values


class RunService:
    def __init__(self, db: Database, gateway: SourceGateway, access: AccessService,
                 data_plane: DataPlaneService | None = None):
        self.db, self.gateway, self.access = db, gateway, access
        self.data_plane = data_plane or DataPlaneService(db, gateway)

    def _definitions(self, functions: list[str], parameters: dict[str, dict[str, Any]],
                     purpose: str, actor: str, input_zone: str | None = None):
        definitions = []
        for code in functions:
            row = self.db.one("SELECT * FROM function_definitions WHERE code=? AND lifecycle='active'", (code,))
            if not row:
                raise RunValidationError(f"active function not found: {code}")
            if row["purpose"] != purpose:
                raise RunValidationError(f"{code} requires purpose {row['purpose']}")
            if input_zone:
                allowed = {
                    "landing": {"01"}, "canonical": {"01", "02", "03", "04"},
                    "dq_passed": {"03", "04"}, "enriched": {"03", "04"},
                    "risk_ready": {"05", "06", "07"},
                }[input_zone]
                if row["stage"] not in allowed:
                    raise RunValidationError(f"stage {row['stage']} cannot consume {input_zone} data")
                if purpose in {"risk_assessment", "case_review"} and input_zone != "risk_ready":
                    raise RunValidationError("risk and selection functions require a risk_ready dataset")
            self.access.require(actor, "run_function", stage=row["stage"], purpose=purpose)
            values = _parameter_values(json.loads(row["parameter_schema_json"]), parameters.get(code, {}))
            definitions.append((row, values))
        extras = set(parameters) - set(functions)
        if extras:
            raise RunValidationError("parameters supplied for unselected functions")
        return definitions

    def create(self, request: RunRequest, actor: str) -> str:
        source = self.db.one("SELECT * FROM sources WHERE source_id=? AND enabled=1", (request.source_id,))
        if not source:
            raise RunValidationError("enabled source not found")
        mapping = self.db.one("SELECT * FROM mapping_profiles WHERE source_id=? AND lifecycle='active'",
                              (request.source_id,))
        if not mapping:
            raise RunValidationError("source has no active mapping profile")
        definitions = self._definitions(request.functions, request.parameters, request.purpose, actor)
        run_id, now = _id(), utc_now()
        with self.db.connect() as connection:
            connection.execute("""INSERT INTO runs VALUES(?,?,?,?,?,?,'queued',?,?,NULL,NULL)""",
                (run_id, request.source_id, mapping["profile_id"], mapping["version"],
                 actor, request.purpose, json.dumps(request.report_ids), now))
            for row, parameters in definitions:
                connection.execute("""INSERT INTO function_runs
                    VALUES(?,?,?,?,?,'queued',?,0,?,NULL,NULL,NULL,NULL,NULL)""",
                    (_id(), run_id, row["code"], row["version"], row["stage"],
                     json.dumps(parameters, sort_keys=True), now))
        self.db.audit(_id(), actor, "CREATE_RUN", f"run:{run_id}", "allowed", request.purpose,
                      {"source_id": request.source_id, "functions": request.functions})
        return run_id

    def create_dataset_run(self, request: DatasetRunRequest, actor: str) -> str:
        dataset = self.data_plane.dataset(request.dataset_id, request.dataset_version)
        if not dataset or dataset["status"] != "published":
            raise RunValidationError("published dataset version not found")
        if dataset["zone"] != request.input_zone:
            raise RunValidationError(f"dataset zone is {dataset['zone']}, not {request.input_zone}")
        lot = self.db.one("SELECT * FROM lots WHERE lot_id=?", (dataset["lot_id"],))
        if not lot:
            raise RunValidationError("dataset lot not found")
        definitions = self._definitions(request.functions, request.parameters, request.purpose,
                                        actor, request.input_zone)
        run_id, now = _id(), utc_now()
        with self.db.connect() as connection:
            connection.execute("""INSERT INTO runs VALUES(?,?,?,?,?,?,'queued',?,?,NULL,NULL)""",
                (run_id, lot["source_id"], lot["mapping_profile_id"], lot["mapping_version"],
                 actor, request.purpose, json.dumps(request.report_ids), now))
            connection.execute("INSERT INTO dataset_run_inputs VALUES(?,?,?,?)",
                (run_id, request.dataset_id, request.dataset_version, request.input_zone))
            for row, parameters in definitions:
                connection.execute("""INSERT INTO function_runs
                    VALUES(?,?,?,?,?,'queued',?,0,?,NULL,NULL,NULL,NULL,NULL)""",
                    (_id(), run_id, row["code"], row["version"], row["stage"],
                     json.dumps(parameters, sort_keys=True), now))
        self.db.audit(_id(), actor, "CREATE_DATASET_RUN", f"run:{run_id}", "allowed",
                      request.purpose, {"dataset_id": request.dataset_id,
                      "dataset_version": request.dataset_version, "input_zone": request.input_zone,
                      "functions": request.functions})
        return run_id

    def get(self, run_id: str) -> dict[str, Any] | None:
        run = self.db.one("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if not run:
            return None
        run["report_ids"] = json.loads(run.pop("report_ids_json") or "null")
        run["function_runs"] = self.db.all(
            "SELECT * FROM function_runs WHERE run_id=? ORDER BY stage,function_code", (run_id,))
        for child in run["function_runs"]:
            child["parameters"] = json.loads(child.pop("parameters_json"))
            child["summary"] = json.loads(child.pop("summary_json") or "null")
            child["artifacts"] = json.loads(child.pop("artifacts_json") or "[]")
        return run

    def list(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT run_id,source_id,requested_by,purpose,status,created_at,completed_at FROM runs ORDER BY created_at DESC")

    def findings(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM findings WHERE run_id=? ORDER BY created_at,finding_id", (run_id,))
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json"))
        return rows

    def _ensure_snapshots(self, run: dict[str, Any]) -> None:
        if self.db.one("SELECT run_id FROM dataset_run_inputs WHERE run_id=?", (run["run_id"],)):
            return
        if self.db.one("SELECT snapshot_id FROM raw_snapshots WHERE run_id=? LIMIT 1", (run["run_id"],)):
            return
        source = self.db.one("SELECT * FROM sources WHERE source_id=?", (run["source_id"],))
        mapping_row = self.db.one("SELECT * FROM mapping_profiles WHERE profile_id=? AND version=?",
                                  (run["mapping_profile_id"], run["mapping_version"]))
        if not source or not mapping_row:
            raise RunValidationError("pinned source mapping is unavailable")
        mapper = CanonicalMapper(json.loads(mapping_row["mapping_json"]))
        wanted = set(json.loads(run["report_ids_json"] or "null") or [])
        rows = []
        for raw in self.gateway.records(source):
            record_id = mapper.source_record_id(raw)
            if wanted and record_id not in wanted:
                continue
            rows.append((_id(), run["run_id"], source["source_id"], record_id,
                         json.dumps(raw, sort_keys=True), snapshot_hash(raw), utc_now()))
        if wanted - {row[3] for row in rows}:
            raise RunValidationError("one or more requested report_ids were not found")
        if not rows:
            raise RunValidationError("source returned no selected records")
        self.db.execute_many("INSERT INTO raw_snapshots VALUES(?,?,?,?,?,?,?)", rows)

    def _canonical_api(self, run: dict[str, Any]) -> CanonicalDataAPI:
        binding = self.db.one("SELECT * FROM dataset_run_inputs WHERE run_id=?", (run["run_id"],))
        if binding:
            return self.data_plane.canonical_api(
                binding["dataset_id"], binding["dataset_version"], binding["input_zone"],
                json.loads(run["report_ids_json"] or "null"),
            )
        mapping = self.db.one("SELECT mapping_json FROM mapping_profiles WHERE profile_id=? AND version=?",
                              (run["mapping_profile_id"], run["mapping_version"]))
        if not mapping:
            raise RunValidationError("pinned mapping no longer exists")
        mapper = CanonicalMapper(json.loads(mapping["mapping_json"]))
        snapshots = self.db.all("SELECT payload_json FROM raw_snapshots WHERE run_id=?", (run["run_id"],))
        return CanonicalDataAPI([mapper.map_report(json.loads(row["payload_json"])) for row in snapshots])

    def process_one(self) -> bool:
        queued = self.db.one("""SELECT fr.*,r.source_id,r.mapping_profile_id,r.mapping_version,
            r.report_ids_json,r.requested_by,r.purpose FROM function_runs fr
            JOIN runs r ON r.run_id=fr.run_id WHERE fr.status='queued'
            ORDER BY fr.created_at,fr.stage,fr.function_code LIMIT 1""")
        if not queued:
            return False
        run_id, child_id = queued["run_id"], queued["function_run_id"]
        self.db.execute("UPDATE runs SET status='running',started_at=COALESCE(started_at,?) WHERE run_id=?",
                        (utc_now(), run_id))
        self.db.execute("UPDATE function_runs SET status='running',attempts=attempts+1,started_at=? WHERE function_run_id=?",
                        (utc_now(), child_id))
        try:
            self._ensure_snapshots(queued)
            api = self._canonical_api(queued)
            handler = HANDLERS.get(queued["handler"] if "handler" in queued else queued["function_code"])
            if not handler:
                definition = self.db.one("SELECT handler FROM function_definitions WHERE code=? AND version=?",
                                         (queued["function_code"], queued["function_version"]))
                handler = HANDLERS.get(definition["handler"] if definition else "")
            if not handler:
                raise RunValidationError("configured handler is not installed")
            result = handler(api, json.loads(queued["parameters_json"]))
            with self.db.connect() as connection:
                connection.execute("""UPDATE function_runs SET status=?,completed_at=?,summary_json=?,
                    artifacts_json=? WHERE function_run_id=?""",
                    (result.status, utc_now(), json.dumps(result.summary, default=str),
                     json.dumps(result.artifacts, default=str), child_id))
                for finding in result.findings:
                    value = finding.model_dump(mode="json")
                    connection.execute("INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (_id(), child_id, run_id, queued["function_code"], value["report_id"],
                         value["entity_id"], value["jurisdiction"], value["severity"], value["code"],
                         value["message"], json.dumps(value["evidence"], sort_keys=True), utc_now()))
                self._persist_business_outputs(connection, queued, result.artifacts, result.findings)
        except Exception as exc:
            self.db.execute("UPDATE function_runs SET status='failed',completed_at=?,error=? WHERE function_run_id=?",
                            (utc_now(), str(exc), child_id))
        remaining = self.db.one("SELECT COUNT(*) AS n FROM function_runs WHERE run_id=? AND status IN ('queued','running')", (run_id,))
        if remaining and remaining["n"] == 0:
            failed = self.db.one("SELECT COUNT(*) AS n FROM function_runs WHERE run_id=? AND status='failed'", (run_id,))
            status = "completed_with_errors" if failed and failed["n"] else "completed"
            self.db.execute("UPDATE runs SET status=?,completed_at=? WHERE run_id=?", (status, utc_now(), run_id))
        return True

    def _persist_business_outputs(self, connection, queued: dict[str, Any],
                                  artifacts: list[dict[str, Any]], findings) -> None:
        binding = self.db.one("SELECT * FROM dataset_run_inputs WHERE run_id=?", (queued["run_id"],))
        if not binding:
            return
        now = utc_now()
        if queued["stage"] in {"05", "06"}:
            for finding in findings:
                result_id = _id()
                connection.execute("INSERT INTO risk_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (result_id, queued["run_id"], queued["function_run_id"], binding["dataset_id"],
                     binding["dataset_version"], finding.report_id, finding.entity_id,
                     finding.jurisdiction, queued["function_code"], finding.severity,
                     json.dumps(finding.model_dump(mode="json"), sort_keys=True), now))
            for artifact in artifacts:
                result_id = _id()
                connection.execute("INSERT INTO risk_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (result_id, queued["run_id"], queued["function_run_id"], binding["dataset_id"],
                     binding["dataset_version"], artifact.get("report_id"), artifact.get("entity_id"),
                     artifact.get("jurisdiction"), queued["function_code"], None,
                     json.dumps(artifact, sort_keys=True), now))
                if artifact.get("type") == "risk_component_score":
                    connection.execute("INSERT INTO risk_score_components VALUES(?,?,?,?,?,?)",
                        (_id(), result_id, queued["function_code"], float(artifact.get("score", 0)),
                         None, f"{artifact.get('component_count', 0)} components fired"))
        if queued["stage"] == "07":
            batch = self.db.one("SELECT selection_batch_id FROM selection_batches WHERE run_id=?", (queued["run_id"],))
            batch_id = batch["selection_batch_id"] if batch else _id()
            if not batch:
                connection.execute("INSERT INTO selection_batches VALUES(?,?,?,?,?,?,?)",
                    (batch_id, queued["run_id"], binding["dataset_id"], binding["dataset_version"],
                     "open", queued["requested_by"], now))
            api = self.data_plane.canonical_api(binding["dataset_id"], binding["dataset_version"])
            for artifact in artifacts:
                if artifact.get("type") != "case_candidate":
                    continue
                report = api.get_report(artifact["report_id"])
                connection.execute("INSERT INTO selection_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (_id(), batch_id, artifact["report_id"], artifact.get("entity_id"),
                     report.reporting_entity_name if report else None, artifact.get("reason_code", queued["function_code"]),
                     artifact.get("score") or artifact.get("maximum_margin"), json.dumps(artifact, sort_keys=True),
                     "pending", None, None, None))


class RunWorker:
    def __init__(self, service: RunService, poll_seconds: float = 0.2):
        self.service, self.poll_seconds = service, poll_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        self.service.db.execute("UPDATE function_runs SET status='queued',started_at=NULL WHERE status='running'")
        while not self._stop.is_set():
            processed = await asyncio.to_thread(self.service.process_one)
            if not processed:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    pass

    def stop(self) -> None:
        self._stop.set()
