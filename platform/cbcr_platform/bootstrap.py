from __future__ import annotations

import json

from .database import Database, utc_now


FUNCTIONS = [
    ("validate_receipt_identity", "01", "Validate receipt identity", "Checks the canonical receipt business identity.", "data_quality", {}),
    ("detect_duplicate_report", "01", "Detect duplicate report", "Detects duplicate canonical business keys.", "data_quality", {}),
    ("normalize_currency", "02", "Normalise currency", "Plans currency normalisation without physical column knowledge.", "data_quality", {"target_currency": {"type": "string", "default": "EUR"}}),
    ("standardize_identifiers", "02", "Standardise identifiers", "Checks identifier normal form.", "data_quality", {}),
    ("resolve_entity", "03", "Resolve entity", "Assesses deterministic entity-link readiness.", "data_quality", {"require_tin": {"type": "boolean", "default": True}}),
    ("enrich_jurisdiction_reference", "03", "Enrich jurisdiction", "Validates canonical jurisdiction reference codes.", "data_quality", {}),
    ("check_completeness", "04", "Check completeness", "Checks required canonical metrics.", "data_quality", {"required_metrics": {"type": "array", "default": ["revenue", "profit_before_tax", "employees"]}}),
    ("check_rpt_share_threshold", "04", "Check related revenue share", "Flags high related-party revenue share.", "data_quality", {"maximum_related_share": {"type": "number", "default": 0.9}}),
    ("analyze_profit_presence_mismatch", "05", "Profit/presence mismatch", "Flags high profit with low employee presence.", "risk_assessment", {"minimum_profit_margin": {"type": "number", "default": 0.25}, "maximum_employees": {"type": "integer", "default": 2}}),
    ("analyze_etr_outlier", "05", "Effective tax rate outlier", "Flags low jurisdiction effective tax rates.", "risk_assessment", {"minimum_etr": {"type": "number", "default": 0.05}}),
    ("cross_match_domestic_turnover", "06", "Cross-match domestic turnover", "Creates a nomenclature-neutral domestic cross-match request.", "risk_assessment", {"domestic_jurisdiction": {"type": "string", "default": "IN"}}),
    ("score_risk_components", "06", "Score risk components", "Produces explainable component scores.", "risk_assessment", {}),
    ("generate_case_candidates", "07", "Generate case candidates", "Produces reviewable candidate artifacts.", "case_review", {"minimum_profit_margin": {"type": "number", "default": 0.4}}),
    ("create_selection_report", "07", "Create selection report", "Creates a minimised selection report.", "case_review", {}),
]


MAPPING_A = {
    "report": {"report_id": "report_key", "message_ref_id": "message_reference",
               "reporting_entity_id": "reporter.id", "reporting_entity_name": "reporter.name",
               "reporting_period_end": "period_end", "reporting_currency": "currency",
               "receiving_jurisdiction": "receiver"},
    "entities": {"path": "constituents", "fields": {"entity_id": "id", "name": "legal_name",
        "tax_jurisdiction": "tax_country", "tin": "tax_id", "role": "role"}},
    "metrics": {"path": "country_totals", "fields": {"jurisdiction": "country", "revenue": "total_revenue",
        "profit_before_tax": "pbt", "income_tax_paid": "tax_paid", "income_tax_accrued": "tax_accrued",
        "employees": "fte", "tangible_assets": "assets", "related_revenue": "related_revenue",
        "unrelated_revenue": "unrelated_revenue"}},
}

MAPPING_B = {
    "report": {"report_id": "submission.uid", "message_ref_id": "submission.msg_ref",
               "reporting_entity_id": "mne.reporting_unit.identifier", "reporting_entity_name": "mne.reporting_unit.label",
               "reporting_period_end": "fiscal.closing_date", "reporting_currency": "fiscal.unit",
               "receiving_jurisdiction": "exchange.destination"},
    "entities": {"path": "mne.members", "fields": {"entity_id": "member_key", "name": "caption",
        "tax_jurisdiction": "residence", "tin": "identifier", "role": "capacity"}},
    "metrics": {"path": "tabulations", "fields": {"jurisdiction": "iso", "revenue": "amounts.revenue_all",
        "profit_before_tax": "amounts.profit", "income_tax_paid": "amounts.cash_tax", "income_tax_accrued": "amounts.tax_expense",
        "employees": "counts.staff", "tangible_assets": "amounts.fixed_assets", "related_revenue": "amounts.revenue_related",
        "unrelated_revenue": "amounts.revenue_unrelated"}},
}

MAPPING_POSTGRESQL = {
    "report": {name: name for name in (
        "report_id", "message_ref_id", "reporting_entity_id", "reporting_entity_name",
        "reporting_period_end", "reporting_currency", "receiving_jurisdiction")},
    "entities": {"path": "entities", "fields": {name: name for name in (
        "entity_id", "name", "tax_jurisdiction", "tin", "role")}},
    "metrics": {"path": "metrics", "fields": {name: name for name in (
        "jurisdiction", "currency_code", "currency_by_measure", "revenue",
        "profit_before_tax", "income_tax_paid", "income_tax_accrued", "employees",
        "tangible_assets", "stated_capital", "accumulated_earnings",
        "related_revenue", "unrelated_revenue")}},
}


def seed(db: Database) -> None:
    now = utc_now()
    with db.connect() as connection:
        sources = (
            ("fixture_alpha", "Fixture schema Alpha", "fixture-json", "schema_alpha.json", None),
            ("fixture_beta", "Fixture schema Beta", "fixture-json", "schema_beta.json", None),
            ("local_cbcr_postgresql", "Local PostgreSQL CbCR XML store", "postgresql-canonical",
             "postgresql://cbcr_user@localhost:5432/cbcr?view=cbcr_canonical.v_api_report_json",
             "env:CBCR_SOURCE_DB_PASSWORD"),
        )
        for source in sources:
            connection.execute("INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,1,?,?)",
                               (*source, now, now))
        for profile_id, source_id, mapping in (("alpha_v1", "fixture_alpha", MAPPING_A),
                                                ("beta_v1", "fixture_beta", MAPPING_B),
                                                ("local_pg_v1", "local_cbcr_postgresql", MAPPING_POSTGRESQL)):
            connection.execute("INSERT OR IGNORE INTO mapping_profiles VALUES(?,?,1,'active',?,?,?)",
                               (profile_id, source_id, json.dumps(mapping, sort_keys=True), now, now))
            object_names = {"report": "report", "entities": "entity", "metrics": "metric"}
            for logical_object, spec in mapping.items():
                fields = spec.get("fields", spec) if isinstance(spec, dict) else {}
                for canonical_field, physical_column in fields.items():
                    if canonical_field == "path":
                        continue
                    connection.execute("""INSERT OR IGNORE INTO mapping_dictionary_entries
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (profile_id, 1, object_names.get(logical_object, logical_object), canonical_field, None,
                         spec.get("path") if isinstance(spec, dict) else None, physical_column,
                         None, 1, f"Maps physical {physical_column} to {canonical_field}", "{}"))
        pipeline_profiles = [
            ("ideal_separated", "Ideal separated data zones",
             ["landing", "canonical", "dq_passed", "enriched", "risk_ready"],
             {"landing": "cbcr_staging", "canonical": "cbcr_canonical", "dq_passed": "cbcr_dq_published",
              "enriched": "cbcr_enriched", "risk_ready": "cbcr_risk_ready"}),
            ("combined_enrichment", "DQ-passed and enrichment combined",
             ["landing", "canonical", "dq_passed", "risk_ready"],
             {"landing": "cbcr_staging", "canonical": "cbcr_working", "dq_passed": "cbcr_working",
              "risk_ready": "cbcr_published"}),
            ("trusted_prevalidated", "Trusted source with upstream DQ evidence",
             ["landing", "canonical", "enriched", "risk_ready"],
             {"landing": "cbcr_inbound", "canonical": "cbcr_working", "enriched": "cbcr_working",
              "risk_ready": "cbcr_published"}),
        ]
        for profile_id, name, route, bindings in pipeline_profiles:
            connection.execute("INSERT OR IGNORE INTO pipeline_profiles VALUES(?,?,?,?,?,?)",
                (profile_id, name, json.dumps(route), json.dumps(bindings, sort_keys=True), 1, now))
        for role_id, name in (("platform_admin", "Platform administrator"), ("dq_analyst", "Data quality analyst"),
                              ("risk_analyst", "Risk analyst"), ("case_manager", "Case manager"),
                              ("auditor", "Auditor")):
            connection.execute("INSERT OR IGNORE INTO roles VALUES(?,?,?)", (role_id, name, now))
        for user_id, name in (("demo", "Demo multi-role user"), ("auditor", "Demo auditor")):
            connection.execute("INSERT OR IGNORE INTO users VALUES(?,?,1,?)", (user_id, name, now))
        for role_id in ("platform_admin", "dq_analyst", "risk_analyst", "case_manager"):
            connection.execute("INSERT OR IGNORE INTO user_roles VALUES('demo',?,?)", (role_id, now))
        connection.execute("INSERT OR IGNORE INTO user_roles VALUES('auditor','auditor',?)", (now,))
        permissions = [
            ("platform_admin", "manage_catalogue", None, None, "allow"),
            ("platform_admin", "manage_access", None, None, "allow"),
            ("platform_admin", "manage_sources", None, None, "allow"),
            ("dq_analyst", "run_function", "*", "data_quality", "allow"),
            ("risk_analyst", "run_function", "*", "risk_assessment", "allow"),
            ("case_manager", "run_function", "07", "case_review", "allow"),
            ("dq_analyst", "view_results", "*", "data_quality", "allow"),
            ("risk_analyst", "view_results", "*", "risk_assessment", "allow"),
            ("case_manager", "view_results", "07", "case_review", "allow"),
            ("auditor", "view_audit", None, None, "allow"),
            ("platform_admin", "manage_pipeline_profiles", None, None, "allow"),
            ("dq_analyst", "manage_datasets", "*", "data_quality", "allow"),
            ("risk_analyst", "manage_datasets", "*", "risk_assessment", "allow"),
            ("case_manager", "manage_selection", "07", "case_review", "allow"),
        ]
        for role_id in ("platform_admin", "dq_analyst", "risk_analyst", "case_manager", "auditor"):
            permissions.extend([
                (role_id, "view_catalogue", None, None, "allow"),
                (role_id, "view_sources", None, None, "allow"),
                (role_id, "view_datasets", None, None, "allow"),
                (role_id, "view_dictionary", None, None, "allow"),
            ])
        for permission in permissions:
            connection.execute("""INSERT INTO role_permissions(role_id,action,stage,purpose,effect)
                SELECT ?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM role_permissions WHERE role_id=? AND action=?
                AND stage IS ? AND purpose IS ? AND effect=?)""", permission + (permission[0], permission[1], permission[2], permission[3], permission[4]))
        for code, stage, name, description, purpose, schema in FUNCTIONS:
            connection.execute("""INSERT OR IGNORE INTO function_definitions
                VALUES(?,1,?,?,?,?,?,?,?,'active','system',?,?)""",
                (code, stage, name, description, code, purpose, json.dumps(schema), "restricted", now, now))
