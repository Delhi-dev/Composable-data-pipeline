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

    def current_user(self, user_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            """SELECT user_id,display_name,external_subject,active,created_at
               FROM cbcr_control.user_account WHERE user_id=%s""",
            (user_id,),
        )
        if not row:
            return None
        row["roles"] = [
            value["role_id"]
            for value in self.db.all(
                """SELECT ur.role_id FROM cbcr_control.user_role ur
                   JOIN cbcr_control.role r ON r.role_id=ur.role_id
                   WHERE ur.user_id=%s AND r.active=true ORDER BY ur.role_id""",
                (user_id,),
            )
        ]
        return row

    def lots(
        self,
        *,
        owner: str | None = None,
        status: str | None = None,
        source_id: str | None = None,
        query: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if owner:
            clauses.append("l.received_by=%s")
            values.append(owner)
        if status:
            clauses.append("l.status=%s")
            values.append(status)
        if source_id:
            clauses.append("l.source_id=%s")
            values.append(source_id)
        if date_from:
            clauses.append("l.received_at >= %s::timestamptz")
            values.append(date_from)
        if date_to:
            clauses.append("l.received_at < (%s::date + interval '1 day')")
            values.append(date_to)
        if query:
            clauses.append(
                "(l.lot_id::text ILIKE %s OR COALESCE(l.external_lot_ref,'') ILIKE %s)"
            )
            needle = f"%{query}%"
            values.extend((needle, needle))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend((page_size, (page - 1) * page_size))
        rows = self.db.all(
            """SELECT l.*,s.name AS source_name
               FROM cbcr_control.lot l
               JOIN cbcr_control.source s ON s.source_id=l.source_id"""
            + where
            + " ORDER BY l.received_at DESC LIMIT %s OFFSET %s",
            tuple(values),
        )
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

    def selection_batches(self, owner: str | None = None) -> list[dict[str, Any]]:
        rows = self.db.all(
            """SELECT sb.*,rs.name AS risk_result_set_name,
                      rs.status AS risk_result_set_status,l.external_lot_ref,
                      (SELECT COUNT(*) FROM cbcr_selection.candidate c
                       WHERE c.selection_batch_id=sb.selection_batch_id) AS candidate_count,
                      (SELECT COUNT(*) FROM cbcr_selection.candidate c
                       WHERE c.selection_batch_id=sb.selection_batch_id AND c.decision='pending') AS pending_count,
                      (SELECT COUNT(*) FROM cbcr_selection.candidate c
                       WHERE c.selection_batch_id=sb.selection_batch_id AND c.decision='selected') AS selected_count,
                      (SELECT COUNT(*) FROM cbcr_selection.candidate c
                       WHERE c.selection_batch_id=sb.selection_batch_id AND c.decision='not_selected') AS not_selected_count,
                      (SELECT COUNT(*) FROM cbcr_selection.candidate c
                       WHERE c.selection_batch_id=sb.selection_batch_id AND c.decision='deferred') AS deferred_count
               FROM cbcr_selection.selection_batch sb
               JOIN cbcr_control.dataset d
                 ON d.dataset_id=sb.dataset_id AND d.version=sb.dataset_version
               JOIN cbcr_control.lot l ON l.lot_id=d.lot_id
               LEFT JOIN cbcr_risk.result_set rs
                 ON rs.result_set_id=sb.risk_result_set_id
               WHERE (%s IS NULL OR l.received_by=%s)
               ORDER BY sb.created_at DESC"""
            , (owner, owner)
        )
        for row in rows:
            for key in ("selection_batch_id", "run_id", "dataset_id", "risk_result_set_id"):
                if row.get(key) is not None:
                    row[key] = str(row[key])
        return rows

    def selection_candidates(
        self,
        batch_id: str,
        *,
        decision: str | None = None,
        minimum_score: float | None = None,
        query: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = ["selection_batch_id=%s"]
        values: list[Any] = [batch_id]
        if decision:
            clauses.append("decision=%s")
            values.append(decision)
        if minimum_score is not None:
            clauses.append("score >= %s")
            values.append(minimum_score)
        if query:
            clauses.append(
                "(report_id ILIKE %s OR COALESCE(entity_id,'') ILIKE %s "
                "OR COALESCE(entity_name,'') ILIKE %s OR reason_code ILIKE %s)"
            )
            needle = f"%{query}%"
            values.extend((needle, needle, needle, needle))
        values.extend((page_size, (page - 1) * page_size))
        rows = self.db.all(
            "SELECT * FROM cbcr_selection.candidate WHERE "
            + " AND ".join(clauses)
            + " ORDER BY report_id,candidate_id LIMIT %s OFFSET %s",
            tuple(values),
        )
        for row in rows:
            row["candidate_id"] = str(row["candidate_id"])
            row["selection_batch_id"] = str(row["selection_batch_id"])
            sources = self.db.all(
                """SELECT rr.risk_result_id,rr.run_id,rr.rule_code,rr.severity,rr.result
                   FROM cbcr_selection.candidate_source_result csr
                   JOIN cbcr_risk.result rr ON rr.risk_result_id=csr.risk_result_id
                   WHERE csr.candidate_id=%s ORDER BY rr.rule_code,rr.risk_result_id""",
                (row["candidate_id"],),
            )
            for source in sources:
                source["risk_result_id"] = str(source["risk_result_id"])
                source["run_id"] = str(source["run_id"])
            row["source_risk_results"] = sources
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

    def set_user_active(self, user_id: str, active: bool, actor: str) -> None:
        with self.db.transaction() as tx:
            row = tx.one(
                """UPDATE cbcr_control.user_account SET active=%s
                   WHERE user_id=%s RETURNING user_id""",
                (active, user_id),
            )
            if not row:
                raise AdminNotFound("user not found")
            self.db.audit(
                new_uuid(), actor, "SET_USER_ACTIVE", f"user:{user_id}", "allowed",
                detail={"active": active}, session=tx,
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

    def audit(
        self,
        limit: int,
        *,
        actor: str | None = None,
        role: str | None = None,
        action: str | None = None,
        decision: str | None = None,
        target: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if actor:
            clauses.append("ae.actor=%s")
            values.append(actor)
        if role:
            clauses.append(
                "EXISTS(SELECT 1 FROM cbcr_control.user_role ur "
                "WHERE ur.user_id=ae.actor AND ur.role_id=%s)"
            )
            values.append(role)
        if action:
            clauses.append("ae.action=%s")
            values.append(action)
        if decision:
            clauses.append("ae.decision=%s")
            values.append(decision)
        if target:
            clauses.append("ae.resource ILIKE %s")
            values.append(f"%{target}%")
        if date_from:
            clauses.append("ae.created_at >= %s::timestamptz")
            values.append(date_from)
        if date_to:
            clauses.append("ae.created_at < (%s::date + interval '1 day')")
            values.append(date_to)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend((limit, (page - 1) * limit))
        rows = self.db.all(
            """SELECT ae.*,
                      COALESCE((SELECT jsonb_agg(ur.role_id ORDER BY ur.role_id)
                                FROM cbcr_control.user_role ur
                                WHERE ur.user_id=ae.actor),'[]'::jsonb) AS roles
               FROM cbcr_control.audit_event ae"""
            + where
            + " ORDER BY ae.created_at DESC LIMIT %s OFFSET %s",
            tuple(values),
        )
        for row in rows:
            row["event_id"] = str(row["event_id"])
        return rows

    def lookup(self, value: str) -> dict[str, Any] | None:
        probes = (
            ("lot", "SELECT lot_id::text AS id FROM cbcr_control.lot WHERE lot_id::text=%s OR external_lot_ref=%s LIMIT 1", "/lifecycle?lot={id}"),
            ("dataset", "SELECT dataset_id::text AS id,version FROM cbcr_control.dataset WHERE dataset_id::text=%s ORDER BY version DESC LIMIT 1", "/datasets/{id}/v{version}/overview"),
            ("run", "SELECT run_id::text AS id FROM cbcr_control.run WHERE run_id::text=%s LIMIT 1", "/runs/{id}"),
            ("risk_result_set", "SELECT result_set_id::text AS id,dataset_id::text AS dataset_id,dataset_version FROM cbcr_risk.result_set WHERE result_set_id::text=%s LIMIT 1", "/cases/{dataset_id}/v{dataset_version}/3?set={id}"),
            ("selection_batch", "SELECT selection_batch_id::text AS id,dataset_id::text AS dataset_id,dataset_version FROM cbcr_selection.selection_batch WHERE selection_batch_id::text=%s LIMIT 1", "/cases/{dataset_id}/v{dataset_version}/4?batch={id}"),
            ("case_set", "SELECT case_set_id::text AS id FROM cbcr_selection.case_set WHERE case_set_id::text=%s LIMIT 1", "/reports/{id}/selected"),
            ("audit_case", "SELECT audit_case_id::text AS id FROM cbcr_selection.audit_case WHERE audit_case_id::text=%s LIMIT 1", "/oversight/lineage?case={id}"),
        )
        for kind, sql, route in probes:
            parameters = (value, value) if kind == "lot" else (value,)
            row = self.db.one(sql, parameters)
            if row:
                return {
                    "type": kind,
                    "id": row["id"],
                    "route": route.format(
                        id=row["id"], version=row.get("version", 1),
                        dataset_id=row.get("dataset_id", ""),
                        dataset_version=row.get("dataset_version", 1),
                    ),
                }
        return None
