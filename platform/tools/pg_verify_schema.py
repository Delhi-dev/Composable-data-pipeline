from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cbcr_platform_pg.config import get_settings  # noqa: E402
from cbcr_platform_pg.database import PostgreSQLDatabase  # noqa: E402


EXPECTED_SCHEMAS = {
    "cbcr_staging",
    "cbcr_canonical",
    "cbcr_dq",
    "cbcr_enriched",
    "cbcr_risk",
    "cbcr_selection",
    "cbcr_control",
    "cbcr_dq_published",
    "cbcr_risk_ready",
}

EXPECTED_TABLES = {
    "cbcr_staging.xml_document",
    "cbcr_staging.xml_validation_issue",
    "cbcr_staging.source_record",
    "cbcr_canonical.report",
    "cbcr_canonical.entity",
    "cbcr_canonical.jurisdiction_metric",
    "cbcr_dq.finding",
    "cbcr_dq.gate_evaluation",
    "cbcr_dq.record_disposition",
    "cbcr_dq.promotion_event",
    "cbcr_dq_published.report",
    "cbcr_dq_published.entity",
    "cbcr_dq_published.jurisdiction_metric",
    "cbcr_enriched.report",
    "cbcr_enriched.entity",
    "cbcr_enriched.jurisdiction_metric",
    "cbcr_enriched.attribute",
    "cbcr_risk_ready.report",
    "cbcr_risk_ready.entity",
    "cbcr_risk_ready.jurisdiction_metric",
    "cbcr_risk.result",
    "cbcr_risk.score_component",
    "cbcr_selection.selection_batch",
    "cbcr_selection.candidate",
    "cbcr_selection.decision_history",
    *{
        "cbcr_control." + name
        for name in (
            "schema_migration source mapping_profile mapping_dictionary_entry "
            "pipeline_profile lot dataset dataset_lineage function_definition run "
            "function_run role user_account user_role role_permission audit_event"
        ).split()
    },
}

EXPECTED_VIEWS = {
    "cbcr_canonical.v_xml_report",
    "cbcr_canonical.v_xml_entity",
    "cbcr_canonical.v_xml_metric",
    "cbcr_canonical.v_api_report_json",
}

REQUIRED_COLUMNS = {
    ("cbcr_control", "schema_migration", "checksum"),
    ("cbcr_control", "function_run", "lease_expires_at"),
    ("cbcr_control", "function_run", "maximum_attempts"),
    ("cbcr_control", "run", "report_ids"),
    ("cbcr_dq", "finding", "function_run_id"),
    ("cbcr_dq", "finding", "dedup_key"),
    ("cbcr_risk", "result", "function_run_id"),
    ("cbcr_risk", "result", "output_key"),
}

REQUIRED_CONSTRAINTS = {
    "fk_enrichment_report",
    "fk_risk_result_report",
    "fk_finding_function_run",
    "fk_risk_function_run",
}

REQUIRED_INDEXES = {
    "idx_pg_function_run_lease",
    "idx_pg_function_run_parent",
    "idx_pg_lineage_parent",
    "idx_pg_lineage_child",
    "idx_pg_finding_run_report",
    "idx_pg_risk_dataset_run_report",
    "idx_pg_audit_time_actor",
    "uq_pg_finding_dedup",
    "uq_pg_risk_output",
    "uq_pg_candidate_logical",
}


def main() -> int:
    settings = get_settings()
    database = PostgreSQLDatabase(settings)
    try:
        database.verify_migrations()
        schemas = {
            row["schema_name"]
            for row in database.all(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'cbcr_%'"
            )
        }
        missing = sorted(EXPECTED_SCHEMAS - schemas)
        if missing:
            raise RuntimeError(f"missing schemas: {', '.join(missing)}")
        relations = {
            f"{row['table_schema']}.{row['table_name']}"
            for row in database.all(
                """SELECT table_schema,table_name FROM information_schema.tables
                   WHERE table_schema LIKE 'cbcr_%' AND table_type='BASE TABLE'"""
            )
        }
        if EXPECTED_TABLES - relations:
            raise RuntimeError(f"missing tables: {', '.join(sorted(EXPECTED_TABLES-relations))}")
        views = {
            f"{row['table_schema']}.{row['table_name']}"
            for row in database.all(
                "SELECT table_schema,table_name FROM information_schema.views WHERE table_schema LIKE 'cbcr_%'"
            )
        }
        if EXPECTED_VIEWS - views:
            raise RuntimeError(f"missing views: {', '.join(sorted(EXPECTED_VIEWS-views))}")
        columns = {
            (row["table_schema"], row["table_name"], row["column_name"])
            for row in database.all(
                "SELECT table_schema,table_name,column_name FROM information_schema.columns WHERE table_schema LIKE 'cbcr_%'"
            )
        }
        if REQUIRED_COLUMNS - columns:
            raise RuntimeError(f"missing columns: {sorted(REQUIRED_COLUMNS-columns)!r}")
        constraints = {
            row["conname"]
            for row in database.all(
                """SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
                   WHERE n.nspname LIKE 'cbcr_%'"""
            )
        }
        if REQUIRED_CONSTRAINTS - constraints:
            raise RuntimeError(f"missing constraints: {', '.join(sorted(REQUIRED_CONSTRAINTS-constraints))}")
        indexes = {
            row["indexname"]
            for row in database.all(
                "SELECT indexname FROM pg_indexes WHERE schemaname LIKE 'cbcr_%'"
            )
        }
        if REQUIRED_INDEXES - indexes:
            raise RuntimeError(f"missing indexes: {', '.join(sorted(REQUIRED_INDEXES-indexes))}")
        trigger_count = database.one(
            """SELECT count(*)::int AS count FROM pg_trigger t
               JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname LIKE 'cbcr_%' AND NOT t.tgisinternal"""
        )["count"]
        if trigger_count < 20:
            raise RuntimeError(f"expected at least 20 immutability triggers; found {trigger_count}")
        privileges = database.all(
            """SELECT nspname,
                      has_schema_privilege(current_user,nspname,'USAGE') AS can_use,
                      has_schema_privilege(current_user,nspname,'CREATE') AS can_create
               FROM pg_namespace WHERE nspname LIKE 'cbcr_%'"""
        )
        if any(not row["can_use"] or row["can_create"] for row in privileges):
            raise RuntimeError("application role schema privileges are broader/narrower than expected")
        summary = database.one(
            """SELECT count(DISTINCT table_schema)::int AS schema_count,
                      count(*)::int AS table_count
               FROM information_schema.tables
               WHERE table_schema LIKE 'cbcr_%' AND table_type='BASE TABLE'"""
        )
        print(
            f"PASS database={settings.database} schemas={summary['schema_count']} "
            f"tables={summary['table_count']} views={len(views)} triggers={trigger_count} "
            "migration=007_application_delete_grants privileges=PASS"
        )
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
