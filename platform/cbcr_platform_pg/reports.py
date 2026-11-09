from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from typing import Any
from uuid import UUID

from .database import PostgreSQLDatabase, utc_now
from .pdf_reports import lineage_pdf, selected_cases_pdf


class CaseReportError(ValueError):
    pass


def _string_ids(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        if row.get(key) is not None:
            row[key] = str(row[key])
    return row


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(_json_value(value), sort_keys=True)
    return _json_value(value)


class CaseReportService:
    """Read-only reports over finalized case-selection provenance."""

    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def _case_set(self, case_set_id: str) -> dict[str, Any]:
        row = self.db.one(
            """SELECT cs.case_set_id,cs.selection_batch_id,cs.version,cs.name,
                      cs.status,cs.selected_count,cs.created_by,cs.created_at,
                      cs.finalized_by,cs.finalized_at,
                      sb.dataset_id,sb.dataset_version,sb.run_id AS candidate_run_id,
                      sb.risk_result_set_id,sb.selection_policy,
                      d.zone AS final_dataset_zone,d.lot_id,l.external_lot_ref,
                      rs.name AS risk_result_set_name,rs.status AS risk_result_set_status,
                      rs.selection_policy AS risk_result_set_policy,rs.approved_by,
                      rs.approved_at
               FROM cbcr_selection.case_set cs
               JOIN cbcr_selection.selection_batch sb
                 ON sb.selection_batch_id=cs.selection_batch_id
               JOIN cbcr_control.dataset d
                 ON d.dataset_id=sb.dataset_id AND d.version=sb.dataset_version
               JOIN cbcr_control.lot l ON l.lot_id=d.lot_id
               LEFT JOIN cbcr_risk.result_set rs
                 ON rs.result_set_id=sb.risk_result_set_id
               WHERE cs.case_set_id=%s""",
            (case_set_id,),
        )
        if not row:
            raise CaseReportError("final case set not found")
        return _string_ids(
            row,
            (
                "case_set_id",
                "selection_batch_id",
                "dataset_id",
                "candidate_run_id",
                "risk_result_set_id",
                "lot_id",
            ),
        )

    def selected_cases(self, case_set_id: str) -> dict[str, Any]:
        case_set = self._case_set(case_set_id)
        cases = self.db.all(
            """SELECT ac.audit_case_id,ac.case_set_id,ac.candidate_id,
                      ac.dataset_id,ac.dataset_version,ac.report_id,ac.entity_id,
                      ac.status,ac.external_reference,ac.case_snapshot,
                      ac.created_at,ac.updated_at,
                      c.entity_name,c.reason_code,c.score,c.decision,
                      c.decision_rationale,c.decided_by,c.decided_at
               FROM cbcr_selection.audit_case ac
               JOIN cbcr_selection.case_set_item csi
                 ON csi.case_set_id=ac.case_set_id AND csi.candidate_id=ac.candidate_id
               JOIN cbcr_selection.candidate c ON c.candidate_id=ac.candidate_id
               WHERE ac.case_set_id=%s
               ORDER BY ac.report_id,ac.entity_id NULLS FIRST,ac.audit_case_id""",
            (case_set_id,),
        )
        sources = self.db.all(
            """SELECT csr.candidate_id,rr.risk_result_id,rr.run_id,rr.rule_code,
                      rr.severity,rr.report_id,rr.entity_id,rr.jurisdiction,
                      rr.result,rr.created_at
               FROM cbcr_selection.case_set_item csi
               JOIN cbcr_selection.candidate_source_result csr
                 ON csr.candidate_id=csi.candidate_id
               JOIN cbcr_risk.result rr ON rr.risk_result_id=csr.risk_result_id
               WHERE csi.case_set_id=%s
               ORDER BY csr.candidate_id,rr.created_at,rr.risk_result_id""",
            (case_set_id,),
        )
        by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for source in sources:
            _string_ids(source, ("candidate_id", "risk_result_id", "run_id"))
            by_candidate[source["candidate_id"]].append(source)
        for item in cases:
            _string_ids(
                item,
                ("audit_case_id", "case_set_id", "candidate_id", "dataset_id"),
            )
            item["source_risk_results"] = by_candidate[item["candidate_id"]]
            item["source_run_ids"] = sorted(
                {source["run_id"] for source in item["source_risk_results"]}
            )
            item["source_functions"] = sorted(
                {source["rule_code"] for source in item["source_risk_results"]}
            )
            snapshot = item.get("case_snapshot") or {}
            item["source_document"] = snapshot.get("source_document")
            item["finalization_rationale"] = snapshot.get("finalization_rationale")
        return _json_value(
            {
                "report_type": "final_selected_cases",
                "report_title": "Final selected cases",
                "generated_at": utc_now(),
                "case_set": case_set,
                "case_count": len(cases),
                "cases": cases,
            }
        )

    def lineage(self, case_set_id: str) -> dict[str, Any]:
        case_set = self._case_set(case_set_id)
        ancestry = self.db.all(
            """WITH RECURSIVE ancestry AS (
                 SELECT d.dataset_id,d.version,d.zone,d.status,d.parent_dataset_id,
                        d.parent_version,d.lot_id,d.pipeline_profile_id,d.report_count,
                        d.created_by,d.created_at,d.published_at,0 AS depth
                 FROM cbcr_control.dataset d
                 WHERE d.dataset_id=%s AND d.version=%s
                 UNION ALL
                 SELECT parent.dataset_id,parent.version,parent.zone,parent.status,
                        parent.parent_dataset_id,parent.parent_version,parent.lot_id,
                        parent.pipeline_profile_id,parent.report_count,parent.created_by,
                        parent.created_at,parent.published_at,a.depth+1
                 FROM ancestry a
                 JOIN cbcr_control.dataset parent
                   ON parent.dataset_id=a.parent_dataset_id
                  AND parent.version=a.parent_version
               )
               SELECT a.*,l.external_lot_ref,dl.lineage_id,dl.transition,
                      dl.reason AS transition_reason,dl.created_by AS transition_by,
                      dl.created_at AS transition_at
               FROM ancestry a
               JOIN cbcr_control.lot l ON l.lot_id=a.lot_id
               LEFT JOIN cbcr_control.dataset_lineage dl
                 ON dl.child_dataset_id=a.dataset_id AND dl.child_version=a.version
               ORDER BY a.depth DESC""",
            (case_set["dataset_id"], case_set["dataset_version"]),
        )
        dataset_keys: set[tuple[str, int]] = set()
        for sequence, dataset in enumerate(ancestry, start=1):
            _string_ids(
                dataset,
                ("dataset_id", "parent_dataset_id", "lot_id", "lineage_id"),
            )
            dataset["sequence"] = sequence
            dataset_keys.add((dataset["dataset_id"], dataset["version"]))

        runs: list[dict[str, Any]] = []
        for dataset in ancestry:
            dataset_runs = self.db.all(
                """SELECT run_id,dataset_id,dataset_version,input_zone,requested_by,
                          purpose,status,selected_functions,parameters,created_at,
                          started_at,completed_at
                   FROM cbcr_control.run
                   WHERE dataset_id=%s AND dataset_version=%s
                   ORDER BY created_at,run_id""",
                (dataset["dataset_id"], dataset["version"]),
            )
            for run in dataset_runs:
                _string_ids(run, ("run_id", "dataset_id"))
                children = self.db.all(
                    """SELECT function_run_id,function_code,function_version,stage,status,
                              parameters,attempt,queued_at,started_at,completed_at,
                              result_summary,error
                       FROM cbcr_control.function_run WHERE run_id=%s
                       ORDER BY stage,function_code,function_version""",
                    (run["run_id"],),
                )
                for child in children:
                    _string_ids(child, ("function_run_id",))
                run["function_runs"] = children
                runs.append(run)

        promotions = self.db.all(
            """SELECT pe.promotion_id,pe.source_dataset_id,pe.source_version,
                      pe.target_dataset_id,pe.target_version,pe.source_zone,
                      pe.target_zone,pe.evaluation_id,pe.promoted_count,
                      pe.rejected_count,pe.requested_by,pe.reason,pe.created_at,
                      ge.run_id AS gate_run_id,ge.policy AS gate_policy,
                      ge.eligible_count,ge.rejected_count AS gate_rejected_count
               FROM cbcr_dq.promotion_event pe
               LEFT JOIN cbcr_dq.gate_evaluation ge
                 ON ge.evaluation_id=pe.evaluation_id
               WHERE pe.target_dataset_id=%s AND pe.target_version=%s
                  OR pe.source_dataset_id=%s AND pe.source_version=%s
               ORDER BY pe.created_at,pe.promotion_id""",
            (
                case_set["dataset_id"],
                case_set["dataset_version"],
                case_set["dataset_id"],
                case_set["dataset_version"],
            ),
        )
        # Fetch every transition in the ancestry, not only the final publication.
        for dataset_id, version in dataset_keys:
            if dataset_id == case_set["dataset_id"] and version == case_set["dataset_version"]:
                continue
            promotions.extend(
                self.db.all(
                    """SELECT pe.promotion_id,pe.source_dataset_id,pe.source_version,
                              pe.target_dataset_id,pe.target_version,pe.source_zone,
                              pe.target_zone,pe.evaluation_id,pe.promoted_count,
                              pe.rejected_count,pe.requested_by,pe.reason,pe.created_at,
                              ge.run_id AS gate_run_id,ge.policy AS gate_policy,
                              ge.eligible_count,ge.rejected_count AS gate_rejected_count
                       FROM cbcr_dq.promotion_event pe
                       LEFT JOIN cbcr_dq.gate_evaluation ge
                         ON ge.evaluation_id=pe.evaluation_id
                       WHERE pe.target_dataset_id=%s AND pe.target_version=%s
                       ORDER BY pe.created_at,pe.promotion_id""",
                    (dataset_id, version),
                )
            )
        unique_promotions: dict[str, dict[str, Any]] = {}
        for promotion in promotions:
            _string_ids(
                promotion,
                (
                    "promotion_id",
                    "source_dataset_id",
                    "target_dataset_id",
                    "evaluation_id",
                    "gate_run_id",
                ),
            )
            unique_promotions[promotion["promotion_id"]] = promotion
        promotions = sorted(
            unique_promotions.values(), key=lambda item: (item["created_at"], item["promotion_id"])
        )

        risk_result_set = None
        if case_set.get("risk_result_set_id"):
            risk_result_set = self.db.one(
                """SELECT result_set_id,dataset_id,dataset_version,name,status,
                          selection_policy,created_by,created_at,approved_by,approved_at
                   FROM cbcr_risk.result_set WHERE result_set_id=%s""",
                (case_set["risk_result_set_id"],),
            )
            if risk_result_set:
                _string_ids(risk_result_set, ("result_set_id", "dataset_id"))
                risk_result_set["included_runs"] = self.db.all(
                    """SELECT r.run_id,r.status,r.purpose,r.selected_functions,
                              r.parameters,r.created_at,r.completed_at
                       FROM cbcr_risk.result_set_run rsr
                       JOIN cbcr_control.run r ON r.run_id=rsr.run_id
                       WHERE rsr.result_set_id=%s ORDER BY r.created_at,r.run_id""",
                    (case_set["risk_result_set_id"],),
                )
                for run in risk_result_set["included_runs"]:
                    _string_ids(run, ("run_id",))

        selected = self.selected_cases(case_set_id)
        return _json_value(
            {
                "report_type": "case_set_lineage",
                "report_title": "Final case-set lineage and execution trace",
                "generated_at": utc_now(),
                "case_set": case_set,
                "dataset_ancestry": ancestry,
                "promotions": promotions,
                "runs": runs,
                "risk_result_set": risk_result_set,
                "selected_cases": selected["cases"],
            }
        )

    def selected_cases_csv(self, case_set_id: str) -> str:
        report = self.selected_cases(case_set_id)
        stream = StringIO()
        fields = [
            "case_set_id",
            "case_set_name",
            "audit_case_id",
            "report_id",
            "entity_id",
            "entity_name",
            "reason_code",
            "score",
            "decision",
            "decision_rationale",
            "decided_by",
            "decided_at",
            "audit_status",
            "external_reference",
            "source_functions",
            "source_run_ids",
            "source_file_name",
            "message_ref_id",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for item in report["cases"]:
            document = item.get("source_document") or {}
            writer.writerow(
                {
                    "case_set_id": report["case_set"]["case_set_id"],
                    "case_set_name": report["case_set"]["name"],
                    "audit_case_id": item["audit_case_id"],
                    "report_id": item["report_id"],
                    "entity_id": item.get("entity_id"),
                    "entity_name": item.get("entity_name"),
                    "reason_code": item["reason_code"],
                    "score": item.get("score"),
                    "decision": item["decision"],
                    "decision_rationale": item.get("decision_rationale"),
                    "decided_by": item.get("decided_by"),
                    "decided_at": item.get("decided_at"),
                    "audit_status": item["status"],
                    "external_reference": item.get("external_reference"),
                    "source_functions": "; ".join(item["source_functions"]),
                    "source_run_ids": "; ".join(item["source_run_ids"]),
                    "source_file_name": document.get("source_file_name"),
                    "message_ref_id": document.get("message_ref_id"),
                }
            )
        return stream.getvalue()

    def selected_cases_pdf(self, case_set_id: str) -> bytes:
        return selected_cases_pdf(self.selected_cases(case_set_id))

    def lineage_csv(self, case_set_id: str) -> str:
        report = self.lineage(case_set_id)
        stream = StringIO()
        fields = [
            "record_type",
            "sequence",
            "zone",
            "dataset_id",
            "dataset_version",
            "parent_dataset_id",
            "transition",
            "transition_reason",
            "run_id",
            "run_purpose",
            "run_status",
            "function_run_id",
            "function_stage",
            "function_code",
            "function_version",
            "function_status",
            "parameters",
            "result_summary",
            "report_id",
            "entity_id",
            "audit_case_id",
            "decision_rationale",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        datasets = {
            (item["dataset_id"], item["version"]): item
            for item in report["dataset_ancestry"]
        }
        runs_by_dataset: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for run in report["runs"]:
            runs_by_dataset[(run["dataset_id"], run["dataset_version"])].append(run)
        for key, dataset in datasets.items():
            dataset_runs = runs_by_dataset.get(key) or [None]
            for run in dataset_runs:
                children = run.get("function_runs", []) if run else []
                for child in children or [None]:
                    writer.writerow(
                        {
                            "record_type": "DATASET_FUNCTION" if child else "DATASET",
                            "sequence": dataset["sequence"],
                            "zone": dataset["zone"],
                            "dataset_id": dataset["dataset_id"],
                            "dataset_version": dataset["version"],
                            "parent_dataset_id": dataset.get("parent_dataset_id"),
                            "transition": dataset.get("transition"),
                            "transition_reason": dataset.get("transition_reason"),
                            "run_id": run.get("run_id") if run else None,
                            "run_purpose": run.get("purpose") if run else None,
                            "run_status": run.get("status") if run else None,
                            "function_run_id": child.get("function_run_id") if child else None,
                            "function_stage": child.get("stage") if child else None,
                            "function_code": child.get("function_code") if child else None,
                            "function_version": child.get("function_version") if child else None,
                            "function_status": child.get("status") if child else None,
                            "parameters": _csv_value(child.get("parameters")) if child else None,
                            "result_summary": _csv_value(child.get("result_summary")) if child else None,
                        }
                    )
        for case in report["selected_cases"]:
            writer.writerow(
                {
                    "record_type": "SELECTED_CASE",
                    "dataset_id": case["dataset_id"],
                    "dataset_version": case["dataset_version"],
                    "report_id": case["report_id"],
                    "entity_id": case.get("entity_id"),
                    "audit_case_id": case["audit_case_id"],
                    "decision_rationale": case.get("decision_rationale"),
                }
            )
        return stream.getvalue()

    def lineage_pdf(self, case_set_id: str) -> bytes:
        return lineage_pdf(self.lineage(case_set_id))
