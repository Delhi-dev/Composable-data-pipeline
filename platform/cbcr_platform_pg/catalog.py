from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse
import re

from cbcr_platform.contracts import FunctionDraft, MappingProfileCreate, SourceCreate
from cbcr_platform.dictionary import canonical_dictionary

from .database import PostgreSQLDatabase, errors, utc_now


class ConflictError(ValueError):
    pass


class CatalogueService:
    def __init__(self, db: PostgreSQLDatabase):
        self.db = db

    def list_sources(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM cbcr_control.source ORDER BY source_id")

    def save_source(self, value: SourceCreate) -> None:
        if value.adapter_type == "postgresql-canonical":
            endpoint = urlparse(value.endpoint_link)
            if endpoint.scheme not in {"postgres", "postgresql"}:
                raise ConflictError("PostgreSQL endpoint must use postgres:// or postgresql://")
            if endpoint.password:
                raise ConflictError("database passwords must use secret_ref, not endpoint_link")
            if not value.secret_ref or not value.secret_ref.startswith("env:"):
                raise ConflictError("PostgreSQL sources require an env:NAME secret reference")
            options = parse_qs(endpoint.query)
            view = options.get("view", [endpoint.fragment])[0]
            if not view or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", view
            ):
                raise ConflictError("PostgreSQL source view must be a safe schema-qualified name")
        self.db.execute(
            """INSERT INTO cbcr_control.source
               (source_id,name,adapter_type,endpoint_link,secret_ref,enabled,created_at,updated_at)
               VALUES(%s,%s,%s,%s,%s,true,%s,%s)
               ON CONFLICT(source_id) DO UPDATE SET
                 name=excluded.name,adapter_type=excluded.adapter_type,
                 endpoint_link=excluded.endpoint_link,secret_ref=excluded.secret_ref,
                 updated_at=excluded.updated_at""",
            (
                value.source_id,
                value.name,
                value.adapter_type,
                value.endpoint_link,
                value.secret_ref,
                utc_now(),
                utc_now(),
            ),
        )

    def save_mapping_draft(self, value: MappingProfileCreate) -> None:
        try:
            self.db.execute(
                """INSERT INTO cbcr_control.mapping_profile
                   (profile_id,source_id,version,lifecycle,mapping,created_at,activated_at)
                   VALUES(%s,%s,%s,'draft',%s,%s,NULL)""",
                (value.profile_id, value.source_id, value.version, value.mapping, utc_now()),
            )
        except errors.UniqueViolation as exc:
            raise ConflictError("mapping profile version already exists") from exc

    def mapping_validation(self, profile_id: str, version: int) -> dict[str, Any]:
        profile = self.db.one(
            """SELECT mapping FROM cbcr_control.mapping_profile
               WHERE profile_id=%s AND version=%s""",
            (profile_id, version),
        )
        if not profile:
            raise ConflictError("mapping profile version not found")
        mapping = profile["mapping"]
        required = {
            (row["logical_object"], row["canonical_field"])
            for row in canonical_dictionary()
            if row["required"]
        }
        present: set[tuple[str, str]] = set()
        object_names = {"report": "report", "entities": "entity", "metrics": "metric"}
        for logical_object, specification in mapping.items():
            fields = specification.get("fields", specification)
            for field in fields:
                if field != "path":
                    present.add((object_names.get(logical_object, logical_object), field))
        missing = [
            {"logical_object": obj, "canonical_field": field}
            for obj, field in sorted(required - present)
        ]
        return {
            "valid": not missing,
            "missing_required_fields": missing,
            "mapped_field_count": len(present),
        }

    def activate_mapping(self, profile_id: str, version: int) -> None:
        validation = self.mapping_validation(profile_id, version)
        if not validation["valid"]:
            missing = ", ".join(
                f"{item['logical_object']}.{item['canonical_field']}"
                for item in validation["missing_required_fields"]
            )
            raise ConflictError(f"mapping is missing required canonical fields: {missing}")
        try:
            with self.db.transaction() as tx:
                row = tx.one(
                    """SELECT source_id,lifecycle FROM cbcr_control.mapping_profile
                       WHERE profile_id=%s AND version=%s FOR UPDATE""",
                    (profile_id, version),
                )
                if not row or row["lifecycle"] != "draft":
                    raise ConflictError("only an existing draft mapping can be activated")
                active = tx.one(
                    """SELECT profile_id FROM cbcr_control.mapping_profile
                       WHERE source_id=%s AND lifecycle='active' FOR UPDATE""",
                    (row["source_id"],),
                )
                if active:
                    raise ConflictError("retire the source's active mapping before activating another")
                tx.execute(
                    """UPDATE cbcr_control.mapping_profile SET lifecycle='active',activated_at=%s
                       WHERE profile_id=%s AND version=%s""",
                    (utc_now(), profile_id, version),
                )
        except errors.UniqueViolation as exc:
            raise ConflictError("source already has an active mapping") from exc

    def list_functions(self, lifecycle: str | None = None) -> list[dict[str, Any]]:
        where = " WHERE lifecycle=%s" if lifecycle else ""
        params = (lifecycle,) if lifecycle else ()
        return self.db.all(
            """SELECT function_code AS code,version,stage,name,description,handler,purpose,
                      parameter_schema,output_classification,lifecycle,created_by,created_at,
                      activated_at,retired_at
               FROM cbcr_control.function_definition"""
            + where
            + " ORDER BY stage,function_code,version",
            params,
        )

    def save_function_draft(self, value: FunctionDraft, actor: str) -> int:
        with self.db.transaction() as tx:
            tx.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"function:{value.code}",)
            )
            latest = tx.one(
                """SELECT COALESCE(MAX(version),0) AS version
                   FROM cbcr_control.function_definition WHERE function_code=%s""",
                (value.code,),
            )
            version = int(latest["version"]) + 1
            tx.execute(
                """INSERT INTO cbcr_control.function_definition
                   (function_code,version,stage,name,description,handler,purpose,
                    parameter_schema,output_classification,lifecycle,created_by,created_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s)""",
                (
                    value.code,
                    version,
                    value.stage,
                    value.name,
                    value.description,
                    value.handler,
                    value.purpose,
                    value.parameter_schema,
                    value.output_classification,
                    actor,
                    utc_now(),
                ),
            )
            return version

    def activate_function(self, code: str, version: int) -> None:
        try:
            with self.db.transaction() as tx:
                row = tx.one(
                    """SELECT lifecycle FROM cbcr_control.function_definition
                       WHERE function_code=%s AND version=%s FOR UPDATE""",
                    (code, version),
                )
                if not row or row["lifecycle"] != "draft":
                    raise ConflictError("only an existing draft function can be activated")
                active = tx.one(
                    """SELECT version FROM cbcr_control.function_definition
                       WHERE function_code=%s AND lifecycle='active' FOR UPDATE""",
                    (code,),
                )
                if active:
                    raise ConflictError("retire the active version before activating another")
                tx.execute(
                    """UPDATE cbcr_control.function_definition
                       SET lifecycle='active',activated_at=%s
                       WHERE function_code=%s AND version=%s""",
                    (utc_now(), code, version),
                )
        except errors.UniqueViolation as exc:
            raise ConflictError("function already has an active version") from exc

    def retire_function(self, code: str, version: int) -> None:
        self.db.execute(
            """UPDATE cbcr_control.function_definition
               SET lifecycle='retired',retired_at=%s
               WHERE function_code=%s AND version=%s AND lifecycle='active'""",
            (utc_now(), code, version),
        )

    def delete_function_draft(self, code: str, version: int) -> None:
        self.db.execute(
            """DELETE FROM cbcr_control.function_definition
               WHERE function_code=%s AND version=%s AND lifecycle='draft'""",
            (code, version),
        )
