from __future__ import annotations

from typing import Any

from cbcr_platform.contracts import FunctionResult

from .database import PostgreSQLDatabase
from .risk_result_sets import RiskResultSetService


class CaseSelectionService:
    def __init__(self, db: PostgreSQLDatabase):
        self.db = db
        self.result_sets = RiskResultSetService(db)

    @staticmethod
    def _score(payload: dict[str, Any]) -> float:
        evidence = payload.get("evidence") or {}
        value = payload.get("score", evidence.get("score", payload.get("maximum_margin", 0)))
        try:
            score = float(value or 0)
        except (TypeError, ValueError):
            return 0
        return score * 100 if 0 < score <= 1 else score

    def generate(
        self,
        dataset_id: str,
        version: int,
        parameters: dict[str, Any],
    ) -> FunctionResult:
        result_set_id = str(parameters.get("risk_result_set_id") or "").strip()
        if not result_set_id:
            raise ValueError("risk_result_set_id is required for governed case generation")
        result_set = self.result_sets.validate_approved(result_set_id, dataset_id, version)
        minimum_score = float(parameters.get("minimum_risk_score", 0))
        allowed_severities = set(parameters.get("allowed_severities") or [])
        allowed_rules = set(parameters.get("allowed_rules") or [])
        rows = self.db.all(
            """SELECT rr.risk_result_id,rr.run_id,rr.report_id,rr.entity_id,rr.jurisdiction,
                      rr.rule_code,rr.severity,rr.result
               FROM cbcr_risk.result rr
               JOIN cbcr_risk.result_set_run rsr ON rsr.run_id=rr.run_id
               WHERE rsr.result_set_id=%s
                 AND rr.dataset_id=%s AND rr.dataset_version=%s
                 AND rr.report_id IS NOT NULL
               ORDER BY rr.report_id,rr.entity_id,rr.rule_code,rr.created_at""",
            (result_set_id, dataset_id, version),
        )
        grouped: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
        for row in rows:
            if allowed_severities and row.get("severity") not in allowed_severities:
                continue
            if allowed_rules and row["rule_code"] not in allowed_rules:
                continue
            row["score"] = self._score(row["result"] or {})
            if row["score"] < minimum_score:
                continue
            row["risk_result_id"] = str(row["risk_result_id"])
            row["run_id"] = str(row["run_id"])
            grouped.setdefault((row["report_id"], row.get("entity_id")), []).append(row)
        artifacts = []
        for (report_id, entity_id), evidence_rows in grouped.items():
            rules = sorted({row["rule_code"] for row in evidence_rows})
            artifacts.append(
                {
                    "type": "case_candidate",
                    "report_id": report_id,
                    "entity_id": entity_id,
                    "reason_code": "APPROVED_RISK_RESULTS",
                    "score": max(row["score"] for row in evidence_rows),
                    "risk_result_set_id": result_set_id,
                    "source_risk_result_ids": [row["risk_result_id"] for row in evidence_rows],
                    "source_run_ids": sorted({row["run_id"] for row in evidence_rows}),
                    "source_rules": rules,
                    "selection_policy": result_set["selection_policy"],
                    "evidence": [
                        {
                            "risk_result_id": row["risk_result_id"],
                            "run_id": row["run_id"],
                            "rule_code": row["rule_code"],
                            "severity": row.get("severity"),
                            "jurisdiction": row.get("jurisdiction"),
                            "score": row["score"],
                            "result": row["result"],
                        }
                        for row in evidence_rows
                    ],
                }
            )
        return FunctionResult(
            summary={
                "candidate_count": len(artifacts),
                "risk_result_set_id": result_set_id,
                "risk_results_considered": len(rows),
                "minimum_risk_score": minimum_score,
            },
            artifacts=artifacts,
        )
