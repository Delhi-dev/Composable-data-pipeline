from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from .canonical import CanonicalDataAPI, CanonicalMapper, SourceGateway, snapshot_hash
from .contracts import CanonicalEntity, CanonicalMetric, CanonicalReport, EnrichmentValue
from .database import Database, utc_now


ZONE_PREFIX = {
    "landing": "stg", "canonical": "can", "dq_passed": "dqp",
    "enriched": "enr", "risk_ready": "rr",
}


class DataPlaneError(ValueError):
    pass


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class DataPlaneService:
    """Governed business-data zones; functions see only CanonicalDataAPI."""

    def __init__(self, db: Database, gateway: SourceGateway):
        self.db, self.gateway = db, gateway

    def ingest(
        self, source_id: str, actor: str, report_ids: list[str] | None = None,
        external_lot_ref: str | None = None, metadata: dict[str, Any] | None = None,
        pipeline_profile_id: str = "ideal_separated",
    ) -> dict[str, Any]:
        source = self.db.one("SELECT * FROM sources WHERE source_id=? AND enabled=1", (source_id,))
        mapping = self.db.one(
            "SELECT * FROM mapping_profiles WHERE source_id=? AND lifecycle='active'", (source_id,),
        )
        if not source or not mapping:
            raise DataPlaneError("enabled source and active mapping profile are required")
        profile = self.db.one("SELECT profile_id FROM pipeline_profiles WHERE profile_id=? AND active=1",
                              (pipeline_profile_id,))
        if not profile:
            raise DataPlaneError("an active pipeline profile is required")
        mapper = CanonicalMapper(json.loads(mapping["mapping_json"]))
        wanted = set(report_ids or [])
        selected: list[tuple[dict[str, Any], CanonicalReport]] = []
        for raw in self.gateway.records(source):
            report = mapper.map_report(raw)
            if not wanted or report.report_id in wanted:
                selected.append((raw, report))
        found = {report.report_id for _, report in selected}
        if wanted - found:
            raise DataPlaneError("one or more requested report_ids were not found")
        if not selected:
            raise DataPlaneError("source returned no selected reports")
        lot_id, landing_id, canonical_id, now = new_id("LOT"), new_id("DS"), new_id("DS"), utc_now()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO lots VALUES(?,?,?,'received',?,?,?,?,?,?)",
                (lot_id, source_id, external_lot_ref, len(selected), json.dumps(metadata or {}, sort_keys=True),
                 mapping["profile_id"], mapping["version"], actor, now),
            )
            self._insert_dataset(connection, landing_id, lot_id, "landing", None, profile["profile_id"],
                                 len(selected), actor, {"source_id": source_id}, now)
            self._store_reports(connection, "landing", landing_id, 1, [report for _, report in selected])
            for raw, report in selected:
                connection.execute("INSERT INTO stg_source_records VALUES(?,?,?,?,?,?)",
                    (landing_id, 1, report.report_id, json.dumps(raw, sort_keys=True), snapshot_hash(raw), now))
            self._insert_dataset(connection, canonical_id, lot_id, "canonical", (landing_id, 1),
                                 profile["profile_id"], len(selected), actor,
                                 {"mapping_profile_id": mapping["profile_id"], "mapping_version": mapping["version"]}, now)
            self._store_reports(connection, "canonical", canonical_id, 1, [report for _, report in selected])
            self._lineage(connection, landing_id, 1, canonical_id, 1, "canonicalise", actor,
                          "Mapped physical source fields to the stable canonical contract", now)
            connection.execute("UPDATE lots SET status='canonicalised' WHERE lot_id=?", (lot_id,))
        return {"lot_id": lot_id, "landing_dataset": {"dataset_id": landing_id, "version": 1},
                "canonical_dataset": {"dataset_id": canonical_id, "version": 1},
                "report_count": len(selected)}

    def _insert_dataset(self, connection, dataset_id: str, lot_id: str, zone: str,
                        parent: tuple[str, int] | None, profile_id: str, count: int,
                        actor: str, metadata: dict[str, Any], now: str) -> None:
        connection.execute("""INSERT INTO datasets VALUES(?,1,?,?,'published',?,?,?,?,?,?,?,?)""",
            (dataset_id, lot_id, zone, parent[0] if parent else None, parent[1] if parent else None,
             profile_id, count, actor, json.dumps(metadata, sort_keys=True), now, now))

    def _lineage(self, connection, parent_id: str, parent_version: int, child_id: str,
                 child_version: int, transition: str, actor: str, reason: str | None, now: str) -> None:
        connection.execute("INSERT INTO dataset_lineage VALUES(?,?,?,?,?,?,?,?,?)",
            (new_id("LIN"), parent_id, parent_version, child_id, child_version,
             transition, reason, actor, now))

    def _store_reports(self, connection, zone: str, dataset_id: str, version: int,
                       reports: list[CanonicalReport]) -> None:
        prefix = ZONE_PREFIX[zone]
        for report in reports:
            connection.execute(f"INSERT INTO {prefix}_reports VALUES(?,?,?,?,?,?,?,?,?)",
                (dataset_id, version, report.report_id, report.message_ref_id,
                 report.reporting_entity_id, report.reporting_entity_name,
                 report.reporting_period_end.isoformat(), report.reporting_currency or "",
                 report.receiving_jurisdiction))
            for entity in report.entities:
                connection.execute(f"INSERT INTO {prefix}_entities VALUES(?,?,?,?,?,?,?,?)",
                    (dataset_id, version, report.report_id, entity.entity_id, entity.name,
                     entity.tax_jurisdiction, entity.tin, entity.role))
            for seq, metric in enumerate(report.metrics, 1):
                connection.execute(f"""INSERT INTO {prefix}_metrics
                    (dataset_id,dataset_version,report_id,metric_seq,jurisdiction,currency_code,
                     currency_by_measure_json,revenue,profit_before_tax,income_tax_paid,
                     income_tax_accrued,employees,tangible_assets,stated_capital,
                     accumulated_earnings,unrelated_revenue,related_revenue)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (dataset_id, version, report.report_id, seq, metric.jurisdiction,
                     metric.currency_code, json.dumps(metric.currency_by_measure, sort_keys=True),
                     _text(metric.revenue), _text(metric.profit_before_tax),
                     _text(metric.income_tax_paid), _text(metric.income_tax_accrued),
                     metric.employees, _text(metric.tangible_assets), _text(metric.stated_capital),
                     _text(metric.accumulated_earnings), _text(metric.unrelated_revenue),
                     _text(metric.related_revenue)))

    def dataset(self, dataset_id: str, version: int = 1) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM datasets WHERE dataset_id=? AND version=?", (dataset_id, version))
        if not row:
            return None
        row["metadata"] = json.loads(row.pop("metadata_json"))
        row["parents"] = self.db.all(
            "SELECT parent_dataset_id,parent_version,transition,reason FROM dataset_lineage WHERE child_dataset_id=? AND child_version=?",
            (dataset_id, version),
        )
        row["children"] = self.db.all(
            "SELECT child_dataset_id,child_version,transition,reason FROM dataset_lineage WHERE parent_dataset_id=? AND parent_version=?",
            (dataset_id, version),
        )
        return row

    def list_datasets(self, lot_id: str | None = None, zone: str | None = None) -> list[dict[str, Any]]:
        clauses, values = [], []
        if lot_id:
            clauses.append("lot_id=?"); values.append(lot_id)
        if zone:
            clauses.append("zone=?"); values.append(zone)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self.db.all("SELECT dataset_id,version,lot_id,zone,status,parent_dataset_id,parent_version,pipeline_profile_id,report_count,created_at FROM datasets" + where + " ORDER BY created_at", tuple(values))

    def canonical_api(self, dataset_id: str, version: int, expected_zone: str | None = None,
                      report_ids: list[str] | None = None) -> CanonicalDataAPI:
        dataset = self.dataset(dataset_id, version)
        if not dataset:
            raise DataPlaneError("dataset version not found")
        if expected_zone and dataset["zone"] != expected_zone:
            raise DataPlaneError(f"dataset is in {dataset['zone']}, not {expected_zone}")
        prefix = ZONE_PREFIX[dataset["zone"]]
        wanted = set(report_ids or [])
        report_rows = self.db.all(f"SELECT * FROM {prefix}_reports WHERE dataset_id=? AND dataset_version=? ORDER BY report_id", (dataset_id, version))
        reports = []
        for row in report_rows:
            if wanted and row["report_id"] not in wanted:
                continue
            entities = self.db.all(f"SELECT * FROM {prefix}_entities WHERE dataset_id=? AND dataset_version=? AND report_id=? ORDER BY entity_id", (dataset_id, version, row["report_id"]))
            metrics = self.db.all(f"SELECT * FROM {prefix}_metrics WHERE dataset_id=? AND dataset_version=? AND report_id=? ORDER BY metric_seq", (dataset_id, version, row["report_id"]))
            reports.append(CanonicalReport(
                report_id=row["report_id"], message_ref_id=row["message_ref_id"],
                reporting_entity_id=row["reporting_entity_id"], reporting_entity_name=row["reporting_entity_name"],
                reporting_period_end=row["reporting_period_end"], reporting_currency=row["reporting_currency"] or None,
                receiving_jurisdiction=row["receiving_jurisdiction"],
                entities=[CanonicalEntity(entity_id=e["entity_id"], name=e["name"], tax_jurisdiction=e["tax_jurisdiction"], tin=e["tin"], role=e["role"]) for e in entities],
                metrics=[CanonicalMetric(**{**{key: m[key] for key in (
                    "jurisdiction", "revenue", "profit_before_tax", "income_tax_paid",
                    "income_tax_accrued", "employees", "tangible_assets", "stated_capital",
                    "accumulated_earnings", "unrelated_revenue", "related_revenue")},
                    "currency_code": m.get("currency_code"),
                    "currency_by_measure": json.loads(m.get("currency_by_measure_json") or "{}")})
                    for m in metrics],
            ))
        if wanted - {report.report_id for report in reports}:
            raise DataPlaneError("one or more requested report_ids are not in the dataset")
        return CanonicalDataAPI(reports)

    def evaluate(self, run_id: str, severities: list[str], actor: str) -> dict[str, Any]:
        binding = self.db.one("SELECT * FROM dataset_run_inputs WHERE run_id=?", (run_id,))
        run = self.db.one("SELECT status FROM runs WHERE run_id=?", (run_id,))
        if not binding or not run or not run["status"].startswith("completed"):
            raise DataPlaneError("a completed dataset run is required")
        reports = self.canonical_api(binding["dataset_id"], binding["dataset_version"]).list_reports()
        placeholders = ",".join("?" for _ in severities)
        findings = self.db.all(
            f"SELECT report_id,code FROM findings WHERE run_id=? AND severity IN ({placeholders})",
            (run_id, *severities),
        ) if severities else []
        blocked: dict[str, list[str]] = {}
        for finding in findings:
            if finding["report_id"]:
                blocked.setdefault(finding["report_id"], []).append(finding["code"])
        evaluation_id, now = new_id("EVAL"), utc_now()
        with self.db.connect() as connection:
            connection.execute("INSERT INTO gate_evaluations VALUES(?,?,?,?,?,?,?,?,?)",
                (evaluation_id, run_id, binding["dataset_id"], binding["dataset_version"],
                 json.dumps({"blocking_severities": severities}), len(reports) - len(blocked),
                 len(blocked), actor, now))
            for report in reports:
                reasons = blocked.get(report.report_id, [])
                connection.execute("INSERT INTO record_dispositions VALUES(?,?,?,?,?)",
                    (evaluation_id, report.report_id, "rejected" if reasons else "eligible",
                     len(reasons), json.dumps(sorted(set(reasons)))))
        return {"evaluation_id": evaluation_id, "eligible_count": len(reports) - len(blocked),
                "rejected_count": len(blocked)}

    def promote(self, dataset_id: str, version: int, target_zone: str, actor: str,
                evaluation_id: str | None = None, enrichment_values: list[EnrichmentValue] | None = None,
                reason: str | None = None) -> dict[str, Any]:
        source = self.dataset(dataset_id, version)
        if not source:
            raise DataPlaneError("source dataset not found")
        profile = self.db.one("SELECT * FROM pipeline_profiles WHERE profile_id=? AND active=1", (source["pipeline_profile_id"],))
        if not profile:
            raise DataPlaneError("dataset pipeline profile is inactive")
        route = json.loads(profile["route_json"])
        try:
            source_pos, target_pos = route.index(source["zone"]), route.index(target_zone)
        except ValueError as exc:
            raise DataPlaneError("source or target zone is not enabled in the pipeline profile") from exc
        if target_pos != source_pos + 1:
            raise DataPlaneError("target must be the next logical zone in the pipeline profile")
        eligible: set[str] | None = None
        rejected_count = 0
        if target_zone == "dq_passed":
            evaluation = self.db.one("SELECT * FROM gate_evaluations WHERE evaluation_id=? AND dataset_id=? AND dataset_version=?", (evaluation_id, dataset_id, version))
            if not evaluation:
                raise DataPlaneError("DQ-passed promotion requires an evaluation for this dataset version")
            eligible = {row["report_id"] for row in self.db.all("SELECT report_id FROM record_dispositions WHERE evaluation_id=? AND disposition='eligible'", (evaluation_id,))}
            rejected_count = evaluation["rejected_count"]
        reports = self.canonical_api(dataset_id, version).list_reports()
        if eligible is not None:
            reports = [report for report in reports if report.report_id in eligible]
        child_id, promotion_id, now = new_id("DS"), new_id("PROM"), utc_now()
        values = enrichment_values or []
        with self.db.connect() as connection:
            self._insert_dataset(connection, child_id, source["lot_id"], target_zone, (dataset_id, version),
                                 source["pipeline_profile_id"], len(reports), actor,
                                 {"evaluation_id": evaluation_id, "enrichment_count": len(values)}, now)
            self._store_reports(connection, target_zone, child_id, 1, reports)
            self._lineage(connection, dataset_id, version, child_id, 1,
                          f"promote_{source['zone']}_to_{target_zone}", actor, reason, now)
            connection.execute("INSERT INTO promotion_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (promotion_id, dataset_id, version, child_id, 1, source["zone"], target_zone,
                 evaluation_id, len(reports), rejected_count, actor, reason, now))
            for value in values:
                connection.execute("INSERT INTO enrichment_attributes VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id("ENR"), child_id, 1, value.report_id, value.entity_id,
                     value.attribute_name, json.dumps(value.value), value.source_ref,
                     value.confidence, now))
        return {"promotion_id": promotion_id, "target_dataset_id": child_id,
                "target_version": 1, "target_zone": target_zone,
                "promoted_count": len(reports), "rejected_count": rejected_count}

    def dispositions(self, evaluation_id: str) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM record_dispositions WHERE evaluation_id=? ORDER BY report_id", (evaluation_id,))
        for row in rows:
            row["reason_codes"] = json.loads(row.pop("reason_codes_json"))
        return rows

    def lineage(self, dataset_id: str, version: int) -> dict[str, Any]:
        return {"dataset": self.dataset(dataset_id, version),
                "promotions": self.db.all("SELECT * FROM promotion_events WHERE source_dataset_id=? OR target_dataset_id=? ORDER BY created_at", (dataset_id, dataset_id))}
