from __future__ import annotations

from typing import Any

from cbcr_platform.contracts import (
    MappingDictionaryRequest,
    PipelineProfileRequest,
    RoleAssignment,
    SelectionDecisionRequest,
    UserCreate,
)

from .database import PostgreSQLDatabase, new_uuid, utc_now


class AdminConflict(ValueError):
    pass


class AdminNotFound(ValueError):
    pass


class AdminService:
    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def mapping_dictionary(self, profile_id: str, version: int) -> list[dict[str, Any]]:
        return self.db.all(
            """SELECT * FROM cbcr_control.mapping_dictionary_entry
               WHERE profile_id=%s AND mapping_version=%s
               ORDER BY logical_object,canonical_field""",
            (profile_id, version),
        )

    def save_mapping_dictionary(
        self, profile_id: str, version: int, value: MappingDictionaryRequest
    ) -> int:
        with self.db.transaction() as tx:
            profile = tx.one(
                """SELECT lifecycle FROM cbcr_control.mapping_profile
                   WHERE profile_id=%s AND version=%s FOR UPDATE""",
                (profile_id, version),
            )
            if not profile or profile["lifecycle"] != "draft":
                raise AdminConflict("dictionary entries can be edited only for draft mappings")
            tx.execute(
                """DELETE FROM cbcr_control.mapping_dictionary_entry
                   WHERE profile_id=%s AND mapping_version=%s""",
                (profile_id, version),
            )
            for entry in value.entries:
                tx.execute(
                    """INSERT INTO cbcr_control.mapping_dictionary_entry
                       (profile_id,mapping_version,logical_object,canonical_field,
                        physical_schema,physical_table,physical_column,data_type,nullable,
                        description,transform)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        profile_id,
                        version,
                        entry.logical_object,
                        entry.canonical_field,
                        entry.physical_schema,
                        entry.physical_table,
                        entry.physical_column,
                        entry.data_type,
                        entry.nullable,
                        entry.description,
                        entry.transform,
                    ),
                )
        return len(value.entries)

    def pipeline_profiles(self) -> list[dict[str, Any]]:
        return self.db.all(
            "SELECT * FROM cbcr_control.pipeline_profile ORDER BY profile_id"
        )

    def save_pipeline_profile(self, value: PipelineProfileRequest) -> None:
        self.db.execute(
            """INSERT INTO cbcr_control.pipeline_profile
               (profile_id,name,route,storage_bindings,active,created_at)
               VALUES(%s,%s,%s,%s,true,%s)
               ON CONFLICT(profile_id) DO UPDATE SET
                 name=excluded.name,route=excluded.route,
                 storage_bindings=excluded.storage_bindings,active=true""",
            (value.profile_id, value.name, value.route, value.storage_bindings, utc_now()),
        )

    def lots(self) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM cbcr_control.lot ORDER BY received_at DESC")
        for row in rows:
            row["lot_id"] = str(row["lot_id"])
        return rows

    def run_binding(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            """SELECT dataset_id,dataset_version FROM cbcr_control.run WHERE run_id=%s""",
            (run_id,),
        )
        if row:
            row["dataset_id"] = str(row["dataset_id"])
        return row

    def risk_results(
        self,
        dataset_id: str | None = None,
        run_id: str | None = None,
        report_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, values = [], []
        if dataset_id:
            clauses.append("dataset_id=%s")
            values.append(dataset_id)
        if run_id:
            clauses.append("run_id=%s")
            values.append(run_id)
        if report_id:
            clauses.append("report_id=%s")
            values.append(report_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.all(
            "SELECT * FROM cbcr_risk.result" + where + " ORDER BY created_at", tuple(values)
        )
        for row in rows:
            for key in ("risk_result_id", "run_id", "function_run_id", "dataset_id"):
                if row.get(key) is not None:
                    row[key] = str(row[key])
            row["score_components"] = self.db.all(
                """SELECT component_id,component_code,score,weight,explanation
                   FROM cbcr_risk.score_component WHERE risk_result_id=%s
                   ORDER BY component_code""",
                (row["risk_result_id"],),
            )
            for component in row["score_components"]:
                component["component_id"] = str(component["component_id"])
        return rows

    def selection_batches(self) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM cbcr_selection.selection_batch ORDER BY created_at DESC"
        )
        for row in rows:
            for key in ("selection_batch_id", "run_id", "dataset_id"):
                row[key] = str(row[key])
        return rows

    def selection_candidates(self, batch_id: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT * FROM cbcr_selection.candidate
               WHERE selection_batch_id=%s ORDER BY report_id,candidate_id""",
            (batch_id,),
        )
        for row in rows:
            row["candidate_id"] = str(row["candidate_id"])
            row["selection_batch_id"] = str(row["selection_batch_id"])
        return rows

    def decide_candidate(
        self, candidate_id: str, value: SelectionDecisionRequest, actor: str
    ) -> dict[str, Any]:
        now = utc_now()
        with self.db.transaction() as tx:
            candidate = tx.one(
                """SELECT candidate_id,decision FROM cbcr_selection.candidate
                   WHERE candidate_id=%s FOR UPDATE""",
                (candidate_id,),
            )
            if not candidate:
                raise AdminNotFound("candidate not found")
            tx.execute(
                """INSERT INTO cbcr_selection.decision_history
                   (decision_history_id,candidate_id,previous_decision,decision,rationale,
                    decided_by,decided_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (
                    new_uuid(),
                    candidate_id,
                    candidate["decision"],
                    value.decision,
                    value.rationale,
                    actor,
                    now,
                ),
            )
            tx.execute(
                """UPDATE cbcr_selection.candidate
                   SET decision=%s,decision_rationale=%s,decided_by=%s,decided_at=%s
                   WHERE candidate_id=%s""",
                (value.decision, value.rationale, actor, now, candidate_id),
            )
            self.db.audit(
                new_uuid(),
                actor,
                "DECIDE_CANDIDATE",
                f"candidate:{candidate_id}",
                "allowed",
                "case_review",
                {"decision": value.decision},
                session=tx,
            )
        return {"candidate_id": candidate_id, "decision": value.decision}

    def users(self) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT user_id,display_name,external_subject,active,created_at
               FROM cbcr_control.user_account ORDER BY user_id"""
        )
        for row in rows:
            row["roles"] = [
                role["role_id"]
                for role in self.db.all(
                    """SELECT role_id FROM cbcr_control.user_role
                       WHERE user_id=%s ORDER BY role_id""",
                    (row["user_id"],),
                )
            ]
        return rows

    def roles(self) -> list[dict[str, Any]]:
        return self.db.all(
            """SELECT role_id,name,description,active,created_at
               FROM cbcr_control.role ORDER BY role_id"""
        )

    def create_user(self, value: UserCreate, actor: str) -> None:
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT INTO cbcr_control.user_account
                   (user_id,display_name,external_subject,active,created_at)
                   VALUES(%s,%s,NULL,true,%s)
                   ON CONFLICT(user_id) DO UPDATE SET
                     display_name=excluded.display_name,active=true""",
                (value.user_id, value.display_name, utc_now()),
            )
            self.db.audit(
                new_uuid(), actor, "SAVE_USER", f"user:{value.user_id}", "allowed", session=tx
            )

    def assign_roles(self, user_id: str, value: RoleAssignment, actor: str) -> int:
        known = {
            row["role_id"]
            for row in self.db.all("SELECT role_id FROM cbcr_control.role WHERE active=true")
        }
        unknown = set(value.role_ids) - known
        if unknown:
            raise AdminConflict(f"unknown roles: {', '.join(sorted(unknown))}")
        with self.db.transaction() as tx:
            if not tx.one(
                "SELECT user_id FROM cbcr_control.user_account WHERE user_id=%s FOR UPDATE",
                (user_id,),
            ):
                raise AdminNotFound("user not found")
            tx.execute("DELETE FROM cbcr_control.user_role WHERE user_id=%s", (user_id,))
            for role_id in value.role_ids:
                tx.execute(
                    """INSERT INTO cbcr_control.user_role
                       (user_id,role_id,assigned_by,assigned_at) VALUES(%s,%s,%s,%s)""",
                    (user_id, role_id, actor, utc_now()),
                )
            self.db.audit(
                new_uuid(),
                actor,
                "ASSIGN_ROLES",
                f"user:{user_id}",
                "allowed",
                detail={"role_ids": value.role_ids},
                session=tx,
            )
        return len(value.role_ids)

    def audit(self, limit: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT * FROM cbcr_control.audit_event
               ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        )
        for row in rows:
            row["event_id"] = str(row["event_id"])
        return rows
