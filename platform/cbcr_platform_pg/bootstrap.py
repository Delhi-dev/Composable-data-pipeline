from __future__ import annotations

from cbcr_platform.bootstrap import FUNCTIONS, MAPPING_A, MAPPING_B, MAPPING_POSTGRESQL

from .database import PostgreSQLDatabase, utc_now

DOMESTIC_FUNCTIONS = (
 ("load_domestic_risk_context", "06", "Load domestic context for screened reports", "Fetches aggregated domestic data only for entities in reports flagged by a completed profit-presence screen; stores an immutable reusable context.", "risk_assessment", {"screening_run_id":{"type":"string","default":""},"fiscal_year":{"type":"integer","default":2025},"match_confidence_floor":{"type":"number","default":0.85}}),
 ("analyze_outbound_low_substance_payments", "06", "Outbound payments to low-substance jurisdictions", "Flags material related-party outbound payments where the group reports low tax or limited substance in the payee jurisdiction.", "risk_assessment", {"domestic_context_id":{"type":"string","default":""},"fiscal_year":{"type":"integer","default":2025},"min_payment_amount":{"type":"number","default":1000000},"low_tax_etr_threshold":{"type":"number","default":0.1},"substance_employee_threshold":{"type":"integer","default":15},"match_confidence_floor":{"type":"number","default":0.85}}),
 ("analyze_interest_stripping", "06", "Interest stripping and thin capitalisation", "Flags material related-party interest where domestic leverage or interest-to-EBITDA is high and payments flow to a low-tax group jurisdiction.", "risk_assessment", {"domestic_context_id":{"type":"string","default":""},"fiscal_year":{"type":"integer","default":2025},"interest_ebitda_cap":{"type":"number","default":0.3},"debt_equity_cap":{"type":"number","default":2.0},"min_interest_amount":{"type":"number","default":1000000},"low_tax_etr_threshold":{"type":"number","default":0.1},"match_confidence_floor":{"type":"number","default":0.85}}),
)


def seed(db: PostgreSQLDatabase) -> None:
    now = utc_now()
    sources = (
        ("fixture_alpha", "Fixture schema Alpha", "fixture-json", "schema_alpha.json", None),
        ("fixture_beta", "Fixture schema Beta", "fixture-json", "schema_beta.json", None),
        (
            "local_cbcr_postgresql",
            "Local PostgreSQL CbCR XML store",
            "postgresql-canonical",
            "postgresql://cbcr_user@localhost:5432/cbcr?view=cbcr_canonical.v_api_report_json",
            "env:CBCR_SOURCE_DB_PASSWORD",
        ),
    )
    mappings = (
        ("alpha_v1", "fixture_alpha", MAPPING_A),
        ("beta_v1", "fixture_beta", MAPPING_B),
        ("local_pg_v1", "local_cbcr_postgresql", MAPPING_POSTGRESQL),
    )
    profiles = (
        (
            "ideal_separated",
            "Ideal separated data zones",
            ["landing", "canonical", "dq_passed", "enriched", "risk_ready"],
            {
                "landing": "cbcr_staging",
                "canonical": "cbcr_canonical",
                "dq_passed": "cbcr_dq_published",
                "enriched": "cbcr_enriched",
                "risk_ready": "cbcr_risk_ready",
            },
        ),
        (
            "combined_enrichment",
            "DQ-passed and enrichment combined",
            ["landing", "canonical", "dq_passed", "risk_ready"],
            {
                "landing": "cbcr_staging",
                "canonical": "cbcr_canonical",
                "dq_passed": "cbcr_dq_published",
                "risk_ready": "cbcr_risk_ready",
            },
        ),
        (
            "trusted_prevalidated",
            "Trusted source with upstream DQ evidence",
            ["landing", "canonical", "enriched", "risk_ready"],
            {
                "landing": "cbcr_staging",
                "canonical": "cbcr_canonical",
                "enriched": "cbcr_enriched",
                "risk_ready": "cbcr_risk_ready",
            },
        ),
    )
    roles = (
        ("platform_admin", "Platform administrator"),
        ("dq_analyst", "Data quality analyst"),
        ("risk_analyst", "Risk analyst"),
        ("case_manager", "Case manager"),
        ("auditor", "Auditor"),
    )
    permissions = [
        ("platform_admin", "manage_catalogue", None, None, "allow"),
        ("platform_admin", "manage_access", None, None, "allow"),
        ("platform_admin", "manage_sources", None, None, "allow"),
        ("platform_admin", "manage_pipeline_profiles", None, None, "allow"),
        ("dq_analyst", "run_function", "*", "data_quality", "allow"),
        ("risk_analyst", "run_function", "*", "risk_assessment", "allow"),
        ("case_manager", "run_function", "07", "case_review", "allow"),
        ("dq_analyst", "view_results", "*", "data_quality", "allow"),
        ("risk_analyst", "view_results", "*", "risk_assessment", "allow"),
        ("case_manager", "view_results", "07", "case_review", "allow"),
        ("auditor", "view_audit", None, None, "allow"),
        ("dq_analyst", "manage_datasets", "*", "data_quality", "allow"),
        ("risk_analyst", "manage_datasets", "*", "risk_assessment", "allow"),
        ("case_manager", "manage_selection", "07", "case_review", "allow"),
    ]
    for role_id, _ in roles:
        permissions.extend(
            [
                (role_id, "view_catalogue", None, None, "allow"),
                (role_id, "view_sources", None, None, "allow"),
                (role_id, "view_datasets", None, None, "allow"),
                (role_id, "view_dictionary", None, None, "allow"),
            ]
        )

    with db.transaction() as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtext('cbcr-platform-bootstrap'))")
        for source in sources:
            tx.execute(
                """INSERT INTO cbcr_control.source
                   (source_id,name,adapter_type,endpoint_link,secret_ref,enabled,created_at,updated_at)
                   VALUES(%s,%s,%s,%s,%s,true,%s,%s) ON CONFLICT(source_id) DO NOTHING""",
                (*source, now, now),
            )
        for profile_id, source_id, mapping in mappings:
            tx.execute(
                """INSERT INTO cbcr_control.mapping_profile
                   (profile_id,source_id,version,lifecycle,mapping,created_at,activated_at)
                   VALUES(%s,%s,1,'active',%s,%s,%s)
                   ON CONFLICT(profile_id,version) DO NOTHING""",
                (profile_id, source_id, mapping, now, now),
            )
            object_names = {"report": "report", "entities": "entity", "metrics": "metric"}
            for logical_object, specification in mapping.items():
                fields = specification.get("fields", specification)
                for canonical_field, physical_column in fields.items():
                    if canonical_field == "path":
                        continue
                    tx.execute(
                        """INSERT INTO cbcr_control.mapping_dictionary_entry
                           (profile_id,mapping_version,logical_object,canonical_field,
                            physical_schema,physical_table,physical_column,data_type,nullable,
                            description,transform)
                           VALUES(%s,1,%s,%s,NULL,%s,%s,NULL,true,%s,'{}'::jsonb)
                           ON CONFLICT(profile_id,mapping_version,logical_object,canonical_field)
                           DO NOTHING""",
                        (
                            profile_id,
                            object_names.get(logical_object, logical_object),
                            canonical_field,
                            specification.get("path") if isinstance(specification, dict) else None,
                            physical_column,
                            f"Maps physical {physical_column} to {canonical_field}",
                        ),
                    )
        for profile_id, name, route, bindings in profiles:
            tx.execute(
                """INSERT INTO cbcr_control.pipeline_profile
                   (profile_id,name,route,storage_bindings,active,created_at)
                   VALUES(%s,%s,%s,%s,true,%s) ON CONFLICT(profile_id) DO NOTHING""",
                (profile_id, name, route, bindings, now),
            )
        for role_id, name in roles:
            tx.execute(
                """INSERT INTO cbcr_control.role(role_id,name,description,active,created_at)
                   VALUES(%s,%s,NULL,true,%s) ON CONFLICT(role_id) DO NOTHING""",
                (role_id, name, now),
            )
        for user_id, display_name in (("demo", "Demo multi-role user"), ("auditor", "Demo auditor")):
            tx.execute(
                """INSERT INTO cbcr_control.user_account
                   (user_id,display_name,external_subject,active,created_at)
                   VALUES(%s,%s,NULL,true,%s) ON CONFLICT(user_id) DO NOTHING""",
                (user_id, display_name, now),
            )
        for role_id in ("platform_admin", "dq_analyst", "risk_analyst", "case_manager"):
            tx.execute(
                """INSERT INTO cbcr_control.user_role(user_id,role_id,assigned_by,assigned_at)
                   VALUES('demo',%s,'bootstrap',%s) ON CONFLICT(user_id,role_id) DO NOTHING""",
                (role_id, now),
            )
        tx.execute(
            """INSERT INTO cbcr_control.user_role(user_id,role_id,assigned_by,assigned_at)
               VALUES('auditor','auditor','bootstrap',%s)
               ON CONFLICT(user_id,role_id) DO NOTHING""",
            (now,),
        )
        for permission in permissions:
            tx.execute(
                """INSERT INTO cbcr_control.role_permission
                   (role_id,action,stage,purpose,effect)
                   SELECT %s,%s,%s,%s,%s
                   WHERE NOT EXISTS(
                     SELECT 1 FROM cbcr_control.role_permission
                     WHERE role_id=%s AND action=%s
                       AND stage IS NOT DISTINCT FROM %s
                       AND purpose IS NOT DISTINCT FROM %s
                       AND effect=%s)""",
                permission + permission,
            )
        for code, stage, name, description, purpose, schema in FUNCTIONS + list(DOMESTIC_FUNCTIONS):
            tx.execute(
                """INSERT INTO cbcr_control.function_definition
                   (function_code,version,stage,name,description,handler,purpose,
                    parameter_schema,output_classification,lifecycle,created_by,
                    created_at,activated_at,retired_at)
                   VALUES(%s,1,%s,%s,%s,%s,%s,%s,'restricted','active','system',%s,%s,NULL)
                   ON CONFLICT(function_code,version) DO NOTHING""",
                (code, stage, name, description, code, purpose, schema, now, now),
            )
