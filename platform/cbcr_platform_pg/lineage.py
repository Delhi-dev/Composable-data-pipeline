from __future__ import annotations

from typing import Any

from .database import PostgreSQLDatabase


def _string_ids(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        if row.get(key) is not None:
            row[key] = str(row[key])
    return row


class LineageService:
    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def audit_case(self, audit_case_id: str) -> dict[str, Any] | None:
        case = self.db.one(
            """SELECT ac.*,cs.selection_batch_id,cs.version AS case_set_version,
                      sb.run_id AS candidate_run_id,sb.risk_result_set_id
               FROM cbcr_selection.audit_case ac
               JOIN cbcr_selection.case_set cs ON cs.case_set_id=ac.case_set_id
               JOIN cbcr_selection.selection_batch sb
                 ON sb.selection_batch_id=cs.selection_batch_id
               WHERE ac.audit_case_id=%s""",
            (audit_case_id,),
        )
        if not case:
            return None
        _string_ids(
            case,
            (
                "audit_case_id",
                "case_set_id",
                "candidate_id",
                "dataset_id",
                "selection_batch_id",
                "candidate_run_id",
                "risk_result_set_id",
            ),
        )
        ancestry = self.db.all(
            """WITH RECURSIVE ancestry AS (
                 SELECT d.dataset_id,d.version,d.zone,d.parent_dataset_id,d.parent_version,
                        d.lot_id,d.created_at,0 AS depth
                 FROM cbcr_control.dataset d
                 WHERE d.dataset_id=%s AND d.version=%s
                 UNION ALL
                 SELECT parent.dataset_id,parent.version,parent.zone,parent.parent_dataset_id,
                        parent.parent_version,parent.lot_id,parent.created_at,a.depth+1
                 FROM ancestry a
                 JOIN cbcr_control.dataset parent
                   ON parent.dataset_id=a.parent_dataset_id
                  AND parent.version=a.parent_version
               )
               SELECT * FROM ancestry ORDER BY depth""",
            (case["dataset_id"], case["dataset_version"]),
        )
        for row in ancestry:
            _string_ids(row, ("dataset_id", "parent_dataset_id", "lot_id"))
        risk_results = self.db.all(
            """SELECT rr.risk_result_id,rr.run_id,rr.rule_code,rr.severity,rr.report_id,
                      rr.entity_id,rr.jurisdiction,rr.result,rr.created_at
               FROM cbcr_selection.candidate_source_result csr
               JOIN cbcr_risk.result rr ON rr.risk_result_id=csr.risk_result_id
               WHERE csr.candidate_id=%s ORDER BY rr.created_at,rr.risk_result_id""",
            (case["candidate_id"],),
        )
        for row in risk_results:
            _string_ids(row, ("risk_result_id", "run_id"))
        decisions = self.db.all(
            """SELECT decision_history_id,previous_decision,decision,rationale,
                      decided_by,decided_at
               FROM cbcr_selection.decision_history
               WHERE candidate_id=%s ORDER BY decided_at,decision_history_id""",
            (case["candidate_id"],),
        )
        for row in decisions:
            _string_ids(row, ("decision_history_id",))
        events = self.db.all(
            """SELECT audit_case_event_id,event_type,previous_status,status,detail,actor,created_at
               FROM cbcr_selection.audit_case_event
               WHERE audit_case_id=%s ORDER BY created_at,audit_case_event_id""",
            (audit_case_id,),
        )
        for row in events:
            _string_ids(row, ("audit_case_event_id",))
        return {
            "audit_case": case,
            "dataset_ancestry": ancestry,
            "source_risk_results": risk_results,
            "decision_history": decisions,
            "audit_case_events": events,
            "source_document": (case.get("case_snapshot") or {}).get("source_document"),
        }
