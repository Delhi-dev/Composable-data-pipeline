from __future__ import annotations

from typing import Any

from cbcr_platform.contracts import AuditCaseStatusRequest, CaseSetFinalizeRequest

from .database import PostgreSQLDatabase, new_uuid, utc_now


class CaseHandoffError(ValueError):
    pass


def _string_ids(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        if row.get(key) is not None:
            row[key] = str(row[key])
    return row


class CaseHandoffService:
    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def finalize(
        self,
        batch_id: str,
        value: CaseSetFinalizeRequest,
        actor: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.db.transaction() as tx:
            batch = tx.one(
                """SELECT selection_batch_id,dataset_id,dataset_version,status,risk_result_set_id
                   FROM cbcr_selection.selection_batch
                   WHERE selection_batch_id=%s FOR UPDATE""",
                (batch_id,),
            )
            if not batch:
                raise CaseHandoffError("selection batch not found")
            if batch["status"] != "open":
                raise CaseHandoffError("only an open selection batch can be finalized")
            counts = tx.one(
                """SELECT COUNT(*) FILTER(WHERE decision='pending') AS pending_count,
                          COUNT(*) FILTER(WHERE decision='selected') AS selected_count
                   FROM cbcr_selection.candidate WHERE selection_batch_id=%s""",
                (batch_id,),
            )
            if counts and counts["pending_count"]:
                raise CaseHandoffError("all candidates must have a decision before finalization")
            if not counts or counts["selected_count"] == 0:
                raise CaseHandoffError("at least one selected candidate is required")
            version_row = tx.one(
                """SELECT COALESCE(MAX(version),0)+1 AS version
                   FROM cbcr_selection.case_set WHERE selection_batch_id=%s""",
                (batch_id,),
            )
            case_set_id, version = new_uuid(), version_row["version"]
            tx.execute(
                """INSERT INTO cbcr_selection.case_set
                   (case_set_id,selection_batch_id,version,name,status,selected_count,
                    created_by,created_at,finalized_by,finalized_at)
                   VALUES(%s,%s,%s,%s,'finalized',%s,%s,%s,%s,%s)""",
                (
                    case_set_id,
                    batch_id,
                    version,
                    value.name,
                    counts["selected_count"],
                    actor,
                    now,
                    actor,
                    now,
                ),
            )
            candidates = tx.all(
                """SELECT * FROM cbcr_selection.candidate
                   WHERE selection_batch_id=%s AND decision='selected'
                   ORDER BY report_id,candidate_id""",
                (batch_id,),
            )
            for candidate in candidates:
                candidate_id, audit_case_id = str(candidate["candidate_id"]), new_uuid()
                sources = tx.all(
                    """SELECT rr.risk_result_id,rr.run_id,rr.rule_code,rr.severity,
                              rr.jurisdiction,rr.result
                       FROM cbcr_selection.candidate_source_result csr
                       JOIN cbcr_risk.result rr ON rr.risk_result_id=csr.risk_result_id
                       WHERE csr.candidate_id=%s ORDER BY rr.rule_code,rr.risk_result_id""",
                    (candidate_id,),
                )
                for source in sources:
                    _string_ids(source, ("risk_result_id", "run_id"))
                origin = tx.one(
                    """SELECT rr.message_ref_id,xd.xml_document_id,xd.source_file_name,
                              xd.source_uri,xd.content_sha256,xd.xml_schema_version,
                              xd.received_at AS xml_received_at
                       FROM cbcr_risk_ready.report rr
                       LEFT JOIN public.cbcr_message_spec ms
                         ON ms.message_ref_id=rr.message_ref_id
                       LEFT JOIN cbcr_staging.xml_document xd
                         ON xd.xml_document_id=ms.xml_document_id
                       WHERE rr.dataset_id=%s AND rr.dataset_version=%s AND rr.report_id=%s
                       ORDER BY xd.xml_document_id NULLS LAST LIMIT 1""",
                    (batch["dataset_id"], batch["dataset_version"], candidate["report_id"]),
                ) or {}
                snapshot = {
                    "candidate": {
                        "candidate_id": candidate_id,
                        "report_id": candidate["report_id"],
                        "entity_id": candidate.get("entity_id"),
                        "entity_name": candidate.get("entity_name"),
                        "reason_code": candidate["reason_code"],
                        "score": candidate.get("score"),
                        "evidence": candidate["evidence"],
                        "decision_rationale": candidate["decision_rationale"],
                        "decided_by": candidate["decided_by"],
                        "decided_at": candidate["decided_at"],
                    },
                    "source_risk_results": sources,
                    "source_document": origin,
                    "finalization_rationale": value.rationale,
                }
                tx.execute(
                    """INSERT INTO cbcr_selection.case_set_item(case_set_id,candidate_id)
                       VALUES(%s,%s)""",
                    (case_set_id, candidate_id),
                )
                tx.execute(
                    """INSERT INTO cbcr_selection.audit_case
                       (audit_case_id,case_set_id,candidate_id,dataset_id,dataset_version,
                        report_id,entity_id,status,external_reference,case_snapshot,created_at,updated_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,'ready_for_handoff',NULL,%s,%s,%s)""",
                    (
                        audit_case_id,
                        case_set_id,
                        candidate_id,
                        batch["dataset_id"],
                        batch["dataset_version"],
                        candidate["report_id"],
                        candidate.get("entity_id"),
                        snapshot,
                        now,
                        now,
                    ),
                )
                tx.execute(
                    """INSERT INTO cbcr_selection.audit_case_event
                       (audit_case_event_id,audit_case_id,event_type,previous_status,status,
                        detail,actor,created_at)
                       VALUES(%s,%s,'CASE_CREATED',NULL,'ready_for_handoff',%s,%s,%s)""",
                    (new_uuid(), audit_case_id, {"case_set_id": case_set_id}, actor, now),
                )
            tx.execute(
                "UPDATE cbcr_selection.selection_batch SET status='finalized' WHERE selection_batch_id=%s",
                (batch_id,),
            )
            self.db.audit(
                new_uuid(),
                actor,
                "FINALIZE_CASE_SET",
                f"case-set:{case_set_id}",
                "allowed",
                "case_review",
                {"selection_batch_id": batch_id, "selected_count": counts["selected_count"]},
                session=tx,
            )
        return self.case_set(case_set_id) or {}

    def case_sets(self) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT cs.*,sb.dataset_id,sb.dataset_version,sb.risk_result_set_id
               FROM cbcr_selection.case_set cs
               JOIN cbcr_selection.selection_batch sb
                 ON sb.selection_batch_id=cs.selection_batch_id
               ORDER BY cs.created_at DESC"""
        )
        return [
            _string_ids(
                row,
                ("case_set_id", "selection_batch_id", "dataset_id", "risk_result_set_id"),
            )
            for row in rows
        ]

    def case_set(self, case_set_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            """SELECT cs.*,sb.dataset_id,sb.dataset_version,sb.risk_result_set_id
               FROM cbcr_selection.case_set cs
               JOIN cbcr_selection.selection_batch sb
                 ON sb.selection_batch_id=cs.selection_batch_id
               WHERE cs.case_set_id=%s""",
            (case_set_id,),
        )
        if not row:
            return None
        _string_ids(
            row,
            ("case_set_id", "selection_batch_id", "dataset_id", "risk_result_set_id"),
        )
        row["cases"] = self.audit_cases(case_set_id=case_set_id)
        return row

    def audit_cases(
        self,
        *,
        case_set_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT ac.audit_case_id,ac.case_set_id,ac.candidate_id,ac.dataset_id,
                      ac.dataset_version,ac.report_id,ac.entity_id,ac.status,
                      ac.external_reference,ac.case_snapshot,ac.created_at,ac.updated_at
               FROM cbcr_selection.audit_case ac
               WHERE (%s IS NULL OR ac.case_set_id=%s)
                 AND (%s IS NULL OR ac.status=%s)
               ORDER BY ac.created_at DESC""",
            (case_set_id, case_set_id, status, status),
        )
        return [
            _string_ids(
                row,
                ("audit_case_id", "case_set_id", "candidate_id", "dataset_id"),
            )
            for row in rows
        ]

    def audit_case(self, audit_case_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            """SELECT audit_case_id,case_set_id,candidate_id,dataset_id,dataset_version,
                      report_id,entity_id,status,external_reference,case_snapshot,
                      created_at,updated_at
               FROM cbcr_selection.audit_case WHERE audit_case_id=%s""",
            (audit_case_id,),
        )
        if not row:
            return None
        return _string_ids(
            row, ("audit_case_id", "case_set_id", "candidate_id", "dataset_id")
        )

    def update_case(
        self,
        audit_case_id: str,
        value: AuditCaseStatusRequest,
        actor: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.db.transaction() as tx:
            current = tx.one(
                "SELECT status FROM cbcr_selection.audit_case WHERE audit_case_id=%s FOR UPDATE",
                (audit_case_id,),
            )
            if not current:
                raise CaseHandoffError("audit case not found")
            tx.execute(
                """UPDATE cbcr_selection.audit_case
                   SET status=%s,external_reference=COALESCE(%s,external_reference),updated_at=%s
                   WHERE audit_case_id=%s""",
                (value.status, value.external_reference, now, audit_case_id),
            )
            tx.execute(
                """INSERT INTO cbcr_selection.audit_case_event
                   (audit_case_event_id,audit_case_id,event_type,previous_status,status,
                    detail,actor,created_at)
                   VALUES(%s,%s,'STATUS_CHANGED',%s,%s,%s,%s,%s)""",
                (
                    new_uuid(),
                    audit_case_id,
                    current["status"],
                    value.status,
                    {"rationale": value.rationale, "external_reference": value.external_reference},
                    actor,
                    now,
                ),
            )
        return self.audit_case(audit_case_id) or {}

    def export_case_set(self, case_set_id: str) -> dict[str, Any]:
        value = self.case_set(case_set_id)
        if not value:
            raise CaseHandoffError("case set not found")
        return {
            "export_version": 1,
            "case_set": {key: item for key, item in value.items() if key != "cases"},
            "cases": value["cases"],
        }
