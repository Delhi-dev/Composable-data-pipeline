from __future__ import annotations

from typing import Any

from cbcr_platform.contracts import RiskResultSetCreate

from .database import PostgreSQLDatabase, new_uuid, utc_now


class RiskResultSetError(ValueError):
    pass


def _string_ids(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    for key in keys:
        if row.get(key) is not None:
            row[key] = str(row[key])
    return row


class RiskResultSetService:
    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def completed_runs(self, dataset_id: str, version: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT r.run_id,r.dataset_id,r.dataset_version,r.status,r.selected_functions,
                      r.parameters,r.created_at,r.completed_at,COUNT(rr.risk_result_id) AS result_count
               FROM cbcr_control.run r
               LEFT JOIN cbcr_risk.result rr ON rr.run_id=r.run_id
               WHERE r.dataset_id=%s AND r.dataset_version=%s
                 AND r.purpose='risk_assessment' AND r.status='completed'
               GROUP BY r.run_id
               ORDER BY r.completed_at DESC,r.created_at DESC""",
            (dataset_id, version),
        )
        return [_string_ids(row, ("run_id", "dataset_id")) for row in rows]

    def create(self, value: RiskResultSetCreate, actor: str) -> dict[str, Any]:
        dataset = self.db.one(
            """SELECT dataset_id,version,zone,status FROM cbcr_control.dataset
               WHERE dataset_id=%s AND version=%s""",
            (value.dataset_id, value.dataset_version),
        )
        if not dataset or dataset["status"] != "published" or dataset["zone"] != "risk_ready":
            raise RiskResultSetError("approved risk-result sets require a published risk_ready dataset")
        unique_run_ids = list(dict.fromkeys(value.run_ids))
        for run_id in unique_run_ids:
            run = self.db.one(
                """SELECT run_id,dataset_id,dataset_version,purpose,status
                   FROM cbcr_control.run WHERE run_id=%s""",
                (run_id,),
            )
            if not run:
                raise RiskResultSetError(f"risk run not found: {run_id}")
            if str(run["dataset_id"]) != value.dataset_id or run["dataset_version"] != value.dataset_version:
                raise RiskResultSetError("all risk runs must belong to the selected dataset version")
            if run["purpose"] != "risk_assessment" or run["status"] != "completed":
                raise RiskResultSetError("all selected runs must be completed risk_assessment runs")
        result_set_id, now = new_uuid(), utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO cbcr_risk.result_set
                   (result_set_id,dataset_id,dataset_version,name,status,selection_policy,
                    created_by,created_at,approved_by,approved_at)
                   VALUES(%s,%s,%s,%s,'draft',%s,%s,%s,NULL,NULL)""",
                (
                    result_set_id,
                    value.dataset_id,
                    value.dataset_version,
                    value.name,
                    value.selection_policy,
                    actor,
                    now,
                ),
            )
            for run_id in unique_run_ids:
                tx.execute(
                    """INSERT INTO cbcr_risk.result_set_run(result_set_id,run_id)
                       VALUES(%s,%s)""",
                    (result_set_id, run_id),
                )
            self.db.audit(
                new_uuid(),
                actor,
                "CREATE_RISK_RESULT_SET",
                f"risk-result-set:{result_set_id}",
                "allowed",
                "case_review",
                {"run_ids": unique_run_ids, "dataset_id": value.dataset_id},
                session=tx,
            )
        return self.get(result_set_id) or {}

    def approve(self, result_set_id: str, actor: str, rationale: str) -> dict[str, Any]:
        now = utc_now()
        with self.db.transaction() as tx:
            row = tx.one(
                "SELECT status FROM cbcr_risk.result_set WHERE result_set_id=%s FOR UPDATE",
                (result_set_id,),
            )
            if not row:
                raise RiskResultSetError("risk-result set not found")
            if row["status"] == "superseded":
                raise RiskResultSetError("superseded risk-result sets cannot be approved")
            tx.execute(
                """UPDATE cbcr_risk.result_set
                   SET status='approved',approved_by=%s,approved_at=COALESCE(approved_at,%s)
                   WHERE result_set_id=%s""",
                (actor, now, result_set_id),
            )
            self.db.audit(
                new_uuid(),
                actor,
                "APPROVE_RISK_RESULT_SET",
                f"risk-result-set:{result_set_id}",
                "allowed",
                "case_review",
                {"rationale": rationale},
                session=tx,
            )
        return self.get(result_set_id) or {}

    def get(self, result_set_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT * FROM cbcr_risk.result_set WHERE result_set_id=%s",
            (result_set_id,),
        )
        if not row:
            return None
        _string_ids(row, ("result_set_id", "dataset_id"))
        run_rows = self.db.all(
            """SELECT rsr.run_id,r.selected_functions,r.parameters,r.completed_at,
                      COUNT(rr.risk_result_id) AS result_count
               FROM cbcr_risk.result_set_run rsr
               JOIN cbcr_control.run r ON r.run_id=rsr.run_id
               LEFT JOIN cbcr_risk.result rr ON rr.run_id=r.run_id
               WHERE rsr.result_set_id=%s
               GROUP BY rsr.run_id,r.run_id,r.selected_functions,r.parameters,r.completed_at
               ORDER BY r.completed_at,r.run_id""",
            (result_set_id,),
        )
        row["runs"] = [_string_ids(item, ("run_id",)) for item in run_rows]
        return row

    def list(
        self, dataset_id: str | None = None, owner: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT rs.result_set_id,rs.dataset_id,rs.dataset_version,rs.name,
                      rs.status,rs.selection_policy,rs.created_by,rs.created_at,
                      rs.approved_by,rs.approved_at
               FROM cbcr_risk.result_set rs
               JOIN cbcr_control.dataset d
                 ON d.dataset_id=rs.dataset_id AND d.version=rs.dataset_version
               JOIN cbcr_control.lot l ON l.lot_id=d.lot_id
               WHERE (%s IS NULL OR rs.dataset_id=%s)
                 AND (%s IS NULL OR l.received_by=%s)
               ORDER BY rs.created_at DESC""",
            (dataset_id, dataset_id, owner, owner),
        )
        values: list[dict[str, Any]] = []
        for row in rows:
            _string_ids(row, ("result_set_id", "dataset_id"))
            run_rows = self.db.all(
                """SELECT rsr.run_id,r.selected_functions,r.completed_at,
                          COUNT(rr.risk_result_id) AS result_count
                   FROM cbcr_risk.result_set_run rsr
                   JOIN cbcr_control.run r ON r.run_id=rsr.run_id
                   LEFT JOIN cbcr_risk.result rr ON rr.run_id=r.run_id
                   WHERE rsr.result_set_id=%s
                   GROUP BY rsr.run_id,r.run_id,r.selected_functions,r.completed_at
                   ORDER BY r.completed_at,r.run_id""",
                (row["result_set_id"],),
            )
            row["runs"] = [_string_ids(item, ("run_id",)) for item in run_rows]
            row["run_ids"] = [item["run_id"] for item in row["runs"]]
            values.append(row)
        return values

    def validate_approved(self, result_set_id: str, dataset_id: str, version: int) -> dict[str, Any]:
        row = self.db.one(
            """SELECT * FROM cbcr_risk.result_set
               WHERE result_set_id=%s AND dataset_id=%s AND dataset_version=%s
                 AND status='approved'""",
            (result_set_id, dataset_id, version),
        )
        if not row:
            raise RiskResultSetError(
                "case generation requires an approved risk-result set for this dataset version"
            )
        return row
