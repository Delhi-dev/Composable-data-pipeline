from __future__ import annotations

from decimal import Decimal
from typing import Any

from psycopg2.extras import Json

from cbcr_platform.canonical import CanonicalDataAPI, CanonicalMapper, SourceGateway, snapshot_hash
from cbcr_platform.contracts import CanonicalEntity, CanonicalMetric, CanonicalReport, EnrichmentValue

from .database import PostgreSQLDatabase, PostgreSQLSession, new_uuid, utc_now


ZONE_SCHEMA = {
    "canonical": "cbcr_canonical",
    "dq_passed": "cbcr_dq_published",
    "enriched": "cbcr_enriched",
    "risk_ready": "cbcr_risk_ready",
}


class DataPlaneError(ValueError):
    pass


def _id(value: Any) -> str | None:
    return None if value is None else str(value)


class DataPlaneService:
    """PostgreSQL governed zones; business functions receive only CanonicalDataAPI."""

    def __init__(self, db: PostgreSQLDatabase, gateway: SourceGateway):
        self.db = db
        self.gateway = gateway

    def ingest(
        self,
        source_id: str,
        actor: str,
        report_ids: list[str] | None = None,
        external_lot_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        pipeline_profile_id: str = "ideal_separated",
    ) -> dict[str, Any]:
        source = self.db.one(
            "SELECT * FROM cbcr_control.source WHERE source_id=%s AND enabled=true",
            (source_id,),
        )
        mapping = self.db.one(
            """SELECT * FROM cbcr_control.mapping_profile
               WHERE source_id=%s AND lifecycle='active'""",
            (source_id,),
        )
        profile = self.db.one(
            """SELECT * FROM cbcr_control.pipeline_profile
               WHERE profile_id=%s AND active=true""",
            (pipeline_profile_id,),
        )
        if not source or not mapping:
            raise DataPlaneError("enabled source and active mapping profile are required")
        if not profile:
            raise DataPlaneError("an active pipeline profile is required")
        mapper = CanonicalMapper(mapping["mapping"])
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

        lot_id, landing_id, canonical_id = new_uuid(), new_uuid(), new_uuid()
        now = utc_now()
        reports = [report for _, report in selected]
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO cbcr_control.lot
                   (lot_id,source_id,external_lot_ref,status,report_count,metadata,
                    mapping_profile_id,mapping_version,received_by,received_at)
                   VALUES(%s,%s,%s,'received',%s,%s,%s,%s,%s,%s)""",
                (
                    lot_id,
                    source_id,
                    external_lot_ref,
                    len(selected),
                    metadata or {},
                    mapping["profile_id"],
                    mapping["version"],
                    actor,
                    now,
                ),
            )
            self._insert_dataset(
                tx,
                landing_id,
                lot_id,
                "landing",
                None,
                pipeline_profile_id,
                len(selected),
                actor,
                {"source_id": source_id},
                now,
            )
            for raw, report in selected:
                tx.execute(
                    """INSERT INTO cbcr_staging.source_record
                       (dataset_id,dataset_version,source_record_id,payload,content_hash,captured_at)
                       VALUES(%s,1,%s,%s,%s,%s)""",
                    (landing_id, report.report_id, raw, snapshot_hash(raw), now),
                )
            self._insert_dataset(
                tx,
                canonical_id,
                lot_id,
                "canonical",
                (landing_id, 1),
                pipeline_profile_id,
                len(selected),
                actor,
                {
                    "mapping_profile_id": mapping["profile_id"],
                    "mapping_version": mapping["version"],
                },
                now,
            )
            self._store_reports(tx, "canonical", canonical_id, 1, reports)
            self._lineage(
                tx,
                landing_id,
                1,
                canonical_id,
                1,
                "canonicalise",
                actor,
                "Mapped physical source fields to the stable canonical contract",
                now,
            )
            tx.execute(
                "UPDATE cbcr_control.lot SET status='canonicalised' WHERE lot_id=%s",
                (lot_id,),
            )
        return {
            "lot_id": lot_id,
            "landing_dataset": {"dataset_id": landing_id, "version": 1},
            "canonical_dataset": {"dataset_id": canonical_id, "version": 1},
            "report_count": len(selected),
        }

    def _insert_dataset(
        self,
        tx: PostgreSQLSession,
        dataset_id: str,
        lot_id: str,
        zone: str,
        parent: tuple[str, int] | None,
        profile_id: str,
        count: int,
        actor: str,
        metadata: dict[str, Any],
        now,
    ) -> None:
        tx.execute(
            """INSERT INTO cbcr_control.dataset
               (dataset_id,version,lot_id,zone,status,parent_dataset_id,parent_version,
                pipeline_profile_id,report_count,created_by,metadata,created_at,published_at)
               VALUES(%s,1,%s,%s,'published',%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                dataset_id,
                lot_id,
                zone,
                parent[0] if parent else None,
                parent[1] if parent else None,
                profile_id,
                count,
                actor,
                metadata,
                now,
                now,
            ),
        )

    def _lineage(
        self,
        tx: PostgreSQLSession,
        parent_id: str,
        parent_version: int,
        child_id: str,
        child_version: int,
        transition: str,
        actor: str,
        reason: str | None,
        now,
    ) -> None:
        tx.execute(
            """INSERT INTO cbcr_control.dataset_lineage
               (lineage_id,parent_dataset_id,parent_version,child_dataset_id,child_version,
                transition,reason,created_by,created_at)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                new_uuid(),
                parent_id,
                parent_version,
                child_id,
                child_version,
                transition,
                reason,
                actor,
                now,
            ),
        )

    def _store_reports(
        self,
        tx: PostgreSQLSession,
        zone: str,
        dataset_id: str,
        version: int,
        reports: list[CanonicalReport],
    ) -> None:
        schema = ZONE_SCHEMA.get(zone)
        if not schema:
            raise DataPlaneError(f"zone has no stable business tables: {zone}")
        for report in reports:
            tx.execute(
                f"""INSERT INTO {schema}.report
                    (dataset_id,dataset_version,report_id,message_ref_id,reporting_entity_id,
                     reporting_entity_name,reporting_period_end,reporting_currency,
                     receiving_jurisdiction)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    dataset_id,
                    version,
                    report.report_id,
                    report.message_ref_id,
                    report.reporting_entity_id,
                    report.reporting_entity_name,
                    report.reporting_period_end,
                    report.reporting_currency,
                    report.receiving_jurisdiction,
                ),
            )
            for entity in report.entities:
                tx.execute(
                    f"""INSERT INTO {schema}.entity
                        (dataset_id,dataset_version,report_id,entity_id,name,tax_jurisdiction,tin,role)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        dataset_id,
                        version,
                        report.report_id,
                        entity.entity_id,
                        entity.name,
                        entity.tax_jurisdiction,
                        entity.tin,
                        entity.role,
                    ),
                )
            for sequence, metric in enumerate(report.metrics, 1):
                tx.execute(
                    f"""INSERT INTO {schema}.jurisdiction_metric
                        (dataset_id,dataset_version,report_id,metric_seq,jurisdiction,
                         currency_code,currency_by_measure,revenue,profit_before_tax,
                         income_tax_paid,income_tax_accrued,employees,tangible_assets,
                         stated_capital,accumulated_earnings,unrelated_revenue,related_revenue)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        dataset_id,
                        version,
                        report.report_id,
                        sequence,
                        metric.jurisdiction,
                        metric.currency_code,
                        metric.currency_by_measure,
                        metric.revenue,
                        metric.profit_before_tax,
                        metric.income_tax_paid,
                        metric.income_tax_accrued,
                        metric.employees,
                        metric.tangible_assets,
                        metric.stated_capital,
                        metric.accumulated_earnings,
                        metric.unrelated_revenue,
                        metric.related_revenue,
                    ),
                )

    def dataset(self, dataset_id: str, version: int = 1) -> dict[str, Any] | None:
        row = self.db.one(
            """SELECT * FROM cbcr_control.dataset
               WHERE dataset_id=%s AND version=%s""",
            (dataset_id, version),
        )
        if not row:
            return None
        row["dataset_id"] = _id(row["dataset_id"])
        row["lot_id"] = _id(row["lot_id"])
        row["parent_dataset_id"] = _id(row["parent_dataset_id"])
        row["parents"] = self.db.all(
            """SELECT parent_dataset_id,parent_version,transition,reason
               FROM cbcr_control.dataset_lineage
               WHERE child_dataset_id=%s AND child_version=%s""",
            (dataset_id, version),
        )
        row["children"] = self.db.all(
            """SELECT child_dataset_id,child_version,transition,reason
               FROM cbcr_control.dataset_lineage
               WHERE parent_dataset_id=%s AND parent_version=%s""",
            (dataset_id, version),
        )
        for relative in row["parents"]:
            relative["parent_dataset_id"] = _id(relative["parent_dataset_id"])
        for relative in row["children"]:
            relative["child_dataset_id"] = _id(relative["child_dataset_id"])
        return row

    def list_datasets(
        self, lot_id: str | None = None, zone: str | None = None
    ) -> list[dict[str, Any]]:
        clauses, values = [], []
        if lot_id:
            clauses.append("lot_id=%s")
            values.append(lot_id)
        if zone:
            clauses.append("zone=%s")
            values.append(zone)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.all(
            """SELECT dataset_id,version,lot_id,zone,status,parent_dataset_id,parent_version,
                      pipeline_profile_id,report_count,created_at
               FROM cbcr_control.dataset"""
            + where
            + " ORDER BY created_at",
            tuple(values),
        )
        for row in rows:
            for key in ("dataset_id", "lot_id", "parent_dataset_id"):
                row[key] = _id(row[key])
        return rows

    def canonical_api(
        self,
        dataset_id: str,
        version: int,
        expected_zone: str | None = None,
        report_ids: list[str] | None = None,
    ) -> CanonicalDataAPI:
        dataset = self.dataset(dataset_id, version)
        if not dataset:
            raise DataPlaneError("dataset version not found")
        if expected_zone and dataset["zone"] != expected_zone:
            raise DataPlaneError(f"dataset is in {dataset['zone']}, not {expected_zone}")
        schema = ZONE_SCHEMA.get(dataset["zone"])
        if not schema:
            raise DataPlaneError(f"dataset zone has no canonical business surface: {dataset['zone']}")
        wanted = set(report_ids or [])
        report_rows = self.db.all(
            f"""SELECT * FROM {schema}.report
                WHERE dataset_id=%s AND dataset_version=%s ORDER BY report_id""",
            (dataset_id, version),
        )
        if wanted:
            report_rows = [row for row in report_rows if row["report_id"] in wanted]
        selected_ids = [row["report_id"] for row in report_rows]
        if wanted - set(selected_ids):
            raise DataPlaneError("one or more requested report_ids are not in the dataset")
        if not selected_ids:
            return CanonicalDataAPI([])
        entities = self.db.all(
            f"""SELECT * FROM {schema}.entity
                WHERE dataset_id=%s AND dataset_version=%s ORDER BY report_id,entity_id""",
            (dataset_id, version),
        )
        metrics = self.db.all(
            f"""SELECT * FROM {schema}.jurisdiction_metric
                WHERE dataset_id=%s AND dataset_version=%s ORDER BY report_id,metric_seq""",
            (dataset_id, version),
        )
        selected = set(selected_ids)
        entity_groups: dict[str, list[CanonicalEntity]] = {key: [] for key in selected_ids}
        metric_groups: dict[str, list[CanonicalMetric]] = {key: [] for key in selected_ids}
        for row in entities:
            if row["report_id"] in selected:
                entity_groups[row["report_id"]].append(
                    CanonicalEntity(
                        entity_id=row["entity_id"],
                        name=row["name"],
                        tax_jurisdiction=row["tax_jurisdiction"],
                        tin=row["tin"],
                        role=row["role"],
                    )
                )
        for row in metrics:
            if row["report_id"] in selected:
                metric_groups[row["report_id"]].append(
                    CanonicalMetric(
                        jurisdiction=row["jurisdiction"],
                        currency_code=row["currency_code"],
                        currency_by_measure=row["currency_by_measure"] or {},
                        revenue=row["revenue"],
                        profit_before_tax=row["profit_before_tax"],
                        income_tax_paid=row["income_tax_paid"],
                        income_tax_accrued=row["income_tax_accrued"],
                        employees=row["employees"],
                        tangible_assets=row["tangible_assets"],
                        stated_capital=row["stated_capital"],
                        accumulated_earnings=row["accumulated_earnings"],
                        unrelated_revenue=row["unrelated_revenue"],
                        related_revenue=row["related_revenue"],
                    )
                )
        reports = [
            CanonicalReport(
                report_id=row["report_id"],
                message_ref_id=row["message_ref_id"],
                reporting_entity_id=row["reporting_entity_id"],
                reporting_entity_name=row["reporting_entity_name"],
                reporting_period_end=row["reporting_period_end"],
                reporting_currency=row["reporting_currency"],
                receiving_jurisdiction=row["receiving_jurisdiction"],
                entities=entity_groups[row["report_id"]],
                metrics=metric_groups[row["report_id"]],
            )
            for row in report_rows
        ]
        return CanonicalDataAPI(reports)

    def evaluate(self, run_id: str, severities: list[str], actor: str) -> dict[str, Any]:
        run = self.db.one(
            """SELECT dataset_id,dataset_version,status FROM cbcr_control.run
               WHERE run_id=%s""",
            (run_id,),
        )
        if not run or not run["status"].startswith("completed"):
            raise DataPlaneError("a completed dataset run is required")
        reports = self.canonical_api(str(run["dataset_id"]), run["dataset_version"]).list_reports()
        findings = self.db.all(
            """SELECT report_id,code FROM cbcr_dq.finding
               WHERE run_id=%s AND severity=ANY(string_to_array(%s, ','))""",
            (run_id, ",".join(severities)),
        ) if severities else []
        blocked: dict[str, list[str]] = {}
        for finding in findings:
            if finding["report_id"]:
                blocked.setdefault(finding["report_id"], []).append(finding["code"])
        evaluation_id, now = new_uuid(), utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO cbcr_dq.gate_evaluation
                   (evaluation_id,run_id,dataset_id,dataset_version,policy,eligible_count,
                    rejected_count,created_by,created_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    evaluation_id,
                    run_id,
                    run["dataset_id"],
                    run["dataset_version"],
                    {"blocking_severities": severities},
                    len(reports) - len(blocked),
                    len(blocked),
                    actor,
                    now,
                ),
            )
            for report in reports:
                reasons = blocked.get(report.report_id, [])
                tx.execute(
                    """INSERT INTO cbcr_dq.record_disposition
                       (evaluation_id,report_id,disposition,blocking_finding_count,reason_codes)
                       VALUES(%s,%s,%s,%s,%s)""",
                    (
                        evaluation_id,
                        report.report_id,
                        "rejected" if reasons else "eligible",
                        len(reasons),
                        sorted(set(reasons)),
                    ),
                )
        return {
            "evaluation_id": evaluation_id,
            "eligible_count": len(reports) - len(blocked),
            "rejected_count": len(blocked),
        }

    def promote(
        self,
        dataset_id: str,
        version: int,
        target_zone: str,
        actor: str,
        evaluation_id: str | None = None,
        enrichment_values: list[EnrichmentValue] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        source = self.dataset(dataset_id, version)
        if not source:
            raise DataPlaneError("source dataset not found")
        profile = self.db.one(
            """SELECT * FROM cbcr_control.pipeline_profile
               WHERE profile_id=%s AND active=true""",
            (source["pipeline_profile_id"],),
        )
        if not profile:
            raise DataPlaneError("dataset pipeline profile is inactive")
        route = profile["route"]
        try:
            source_pos, target_pos = route.index(source["zone"]), route.index(target_zone)
        except ValueError as exc:
            raise DataPlaneError("source or target zone is not enabled in the pipeline profile") from exc
        if target_pos != source_pos + 1:
            raise DataPlaneError("target must be the next logical zone in the pipeline profile")
        if target_zone not in ZONE_SCHEMA:
            raise DataPlaneError("target zone is not supported by PostgreSQL publication")

        existing = self.db.one(
            """SELECT promotion_id,target_dataset_id,target_version,target_zone,
                      promoted_count,rejected_count
               FROM cbcr_dq.promotion_event
               WHERE source_dataset_id=%s AND source_version=%s AND target_zone=%s
                 AND evaluation_id IS NOT DISTINCT FROM %s""",
            (dataset_id, version, target_zone, evaluation_id),
        )
        if existing:
            return {key: _id(value) if key.endswith("_id") else value for key, value in existing.items()}

        eligible: set[str] | None = None
        rejected_count = 0
        if target_zone == "dq_passed":
            evaluation = self.db.one(
                """SELECT * FROM cbcr_dq.gate_evaluation
                   WHERE evaluation_id=%s AND dataset_id=%s AND dataset_version=%s""",
                (evaluation_id, dataset_id, version),
            )
            if not evaluation:
                raise DataPlaneError("DQ-passed promotion requires an evaluation for this dataset version")
            eligible = {
                row["report_id"]
                for row in self.db.all(
                    """SELECT report_id FROM cbcr_dq.record_disposition
                       WHERE evaluation_id=%s AND disposition='eligible'""",
                    (evaluation_id,),
                )
            }
            rejected_count = evaluation["rejected_count"]

        reports = self.canonical_api(dataset_id, version).list_reports()
        if eligible is not None:
            reports = [report for report in reports if report.report_id in eligible]
        child_id, promotion_id, now = new_uuid(), new_uuid(), utc_now()
        values = enrichment_values or []
        with self.db.transaction() as tx:
            self._insert_dataset(
                tx,
                child_id,
                source["lot_id"],
                target_zone,
                (dataset_id, version),
                source["pipeline_profile_id"],
                len(reports),
                actor,
                {"evaluation_id": evaluation_id, "enrichment_count": len(values)},
                now,
            )
            self._store_reports(tx, target_zone, child_id, 1, reports)
            self._lineage(
                tx,
                dataset_id,
                version,
                child_id,
                1,
                f"promote_{source['zone']}_to_{target_zone}",
                actor,
                reason,
                now,
            )
            tx.execute(
                """INSERT INTO cbcr_dq.promotion_event
                   (promotion_id,source_dataset_id,source_version,target_dataset_id,target_version,
                    source_zone,target_zone,evaluation_id,promoted_count,rejected_count,
                    requested_by,reason,created_at)
                   VALUES(%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    promotion_id,
                    dataset_id,
                    version,
                    child_id,
                    source["zone"],
                    target_zone,
                    evaluation_id,
                    len(reports),
                    rejected_count,
                    actor,
                    reason,
                    now,
                ),
            )
            for value in values:
                tx.execute(
                    """INSERT INTO cbcr_enriched.attribute
                       (enrichment_id,dataset_id,dataset_version,report_id,entity_id,
                        attribute_name,value,source_ref,confidence,created_at)
                       VALUES(%s,%s,1,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        new_uuid(),
                        child_id,
                        value.report_id,
                        value.entity_id,
                        value.attribute_name,
                        Json(value.value),
                        value.source_ref,
                        value.confidence,
                        now,
                    ),
                )
        return {
            "promotion_id": promotion_id,
            "target_dataset_id": child_id,
            "target_version": 1,
            "target_zone": target_zone,
            "promoted_count": len(reports),
            "rejected_count": rejected_count,
        }

    def dispositions(self, evaluation_id: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT evaluation_id,report_id,disposition,blocking_finding_count,reason_codes
               FROM cbcr_dq.record_disposition
               WHERE evaluation_id=%s ORDER BY report_id""",
            (evaluation_id,),
        )
        for row in rows:
            row["evaluation_id"] = _id(row["evaluation_id"])
        return rows

    def lineage(self, dataset_id: str, version: int) -> dict[str, Any]:
        promotions = self.db.all(
            """SELECT * FROM cbcr_dq.promotion_event
               WHERE source_dataset_id=%s OR target_dataset_id=%s ORDER BY created_at""",
            (dataset_id, dataset_id),
        )
        for row in promotions:
            for key in (
                "promotion_id",
                "source_dataset_id",
                "target_dataset_id",
                "evaluation_id",
            ):
                row[key] = _id(row[key])
        return {"dataset": self.dataset(dataset_id, version), "promotions": promotions}
