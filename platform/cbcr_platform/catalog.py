from __future__ import annotations

import json
from typing import Any

from .contracts import FunctionDraft, MappingProfileCreate, SourceCreate
from .dictionary import canonical_dictionary
from .database import Database, utc_now


class ConflictError(ValueError):
    pass


class CatalogueService:
    def __init__(self, db: Database):
        self.db = db

    def list_sources(self) -> list[dict[str, Any]]:
        return self.db.all("SELECT * FROM sources ORDER BY source_id")

    def save_source(self, value: SourceCreate) -> None:
        now = utc_now()
        self.db.execute(
            """INSERT INTO sources(source_id,name,adapter_type,endpoint_link,secret_ref,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET name=excluded.name,
               adapter_type=excluded.adapter_type,endpoint_link=excluded.endpoint_link,
               secret_ref=excluded.secret_ref,updated_at=excluded.updated_at""",
            (value.source_id, value.name, value.adapter_type, value.endpoint_link,
             value.secret_ref, now, now),
        )

    def save_mapping_draft(self, value: MappingProfileCreate) -> None:
        self.db.execute(
            "INSERT INTO mapping_profiles VALUES(?,?,?,?,?,?,NULL)",
            (value.profile_id, value.source_id, value.version, "draft",
             json.dumps(value.mapping, sort_keys=True), utc_now()),
        )

    def mapping_validation(self, profile_id: str, version: int) -> dict[str, Any]:
        profile = self.db.one("SELECT * FROM mapping_profiles WHERE profile_id=? AND version=?",
                              (profile_id, version))
        if not profile:
            raise ConflictError("mapping profile version not found")
        mapping = json.loads(profile["mapping_json"])
        required = {(row["logical_object"], row["canonical_field"])
                    for row in canonical_dictionary() if row["required"]}
        present = set()
        object_names = {"report": "report", "entities": "entity", "metrics": "metric"}
        for logical_object, spec in mapping.items():
            fields = spec.get("fields", spec) if isinstance(spec, dict) else {}
            for field in fields:
                if field != "path":
                    present.add((object_names.get(logical_object, logical_object), field))
        missing = [{"logical_object": obj, "canonical_field": field}
                   for obj, field in sorted(required - present)]
        return {"valid": not missing, "missing_required_fields": missing,
                "mapped_field_count": len(present)}

    def activate_mapping(self, profile_id: str, version: int) -> None:
        row = self.db.one("SELECT * FROM mapping_profiles WHERE profile_id=? AND version=?",
                          (profile_id, version))
        if not row or row["lifecycle"] != "draft":
            raise ConflictError("only an existing draft mapping can be activated")
        validation = self.mapping_validation(profile_id, version)
        if not validation["valid"]:
            missing = ", ".join(
                f"{item['logical_object']}.{item['canonical_field']}"
                for item in validation["missing_required_fields"]
            )
            raise ConflictError(f"mapping is missing required canonical fields: {missing}")
        active = self.db.one("SELECT profile_id FROM mapping_profiles WHERE source_id=? AND lifecycle='active'",
                             (row["source_id"],))
        if active:
            raise ConflictError("retire the source's active mapping before activating another")
        self.db.execute("UPDATE mapping_profiles SET lifecycle='active',activated_at=? WHERE profile_id=? AND version=?",
                        (utc_now(), profile_id, version))

    def list_functions(self, lifecycle: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM function_definitions"
        params: tuple[Any, ...] = ()
        if lifecycle:
            sql += " WHERE lifecycle=?"
            params = (lifecycle,)
        rows = self.db.all(sql + " ORDER BY stage,code,version", params)
        for row in rows:
            row["parameter_schema"] = json.loads(row.pop("parameter_schema_json"))
        return rows

    def save_function_draft(self, value: FunctionDraft, actor: str) -> int:
        latest = self.db.one("SELECT MAX(version) AS version FROM function_definitions WHERE code=?",
                             (value.code,))
        version = int(latest["version"] or 0) + 1
        self.db.execute(
            "INSERT INTO function_definitions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (value.code, version, value.stage, value.name, value.description, value.handler,
             value.purpose, json.dumps(value.parameter_schema, sort_keys=True),
             value.output_classification, "draft", actor, utc_now()),
        )
        return version

    def activate_function(self, code: str, version: int) -> None:
        row = self.db.one("SELECT lifecycle FROM function_definitions WHERE code=? AND version=?",
                          (code, version))
        if not row or row["lifecycle"] != "draft":
            raise ConflictError("only an existing draft function can be activated")
        active = self.db.one("SELECT version FROM function_definitions WHERE code=? AND lifecycle='active'", (code,))
        if active:
            raise ConflictError("retire the active version before activating another")
        self.db.execute("UPDATE function_definitions SET lifecycle='active',activated_at=? WHERE code=? AND version=?",
                        (utc_now(), code, version))

    def retire_function(self, code: str, version: int) -> None:
        self.db.execute("UPDATE function_definitions SET lifecycle='retired' WHERE code=? AND version=? AND lifecycle='active'",
                        (code, version))

    def delete_function_draft(self, code: str, version: int) -> None:
        self.db.execute("DELETE FROM function_definitions WHERE code=? AND version=? AND lifecycle='draft'",
                        (code, version))
