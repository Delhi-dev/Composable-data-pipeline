from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY, name TEXT NOT NULL, adapter_type TEXT NOT NULL,
  endpoint_link TEXT NOT NULL, secret_ref TEXT, enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mapping_profiles (
  profile_id TEXT NOT NULL, source_id TEXT NOT NULL, version INTEGER NOT NULL,
  lifecycle TEXT NOT NULL CHECK(lifecycle IN ('draft','active','retired')),
  mapping_json TEXT NOT NULL, created_at TEXT NOT NULL, activated_at TEXT,
  PRIMARY KEY(profile_id,version), FOREIGN KEY(source_id) REFERENCES sources(source_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_mapping
  ON mapping_profiles(source_id) WHERE lifecycle='active';
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roles (
  role_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_roles (
  user_id TEXT NOT NULL, role_id TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(user_id,role_id), FOREIGN KEY(user_id) REFERENCES users(user_id),
  FOREIGN KEY(role_id) REFERENCES roles(role_id)
);
CREATE TABLE IF NOT EXISTS role_permissions (
  permission_id INTEGER PRIMARY KEY AUTOINCREMENT, role_id TEXT NOT NULL,
  action TEXT NOT NULL, stage TEXT, purpose TEXT, effect TEXT NOT NULL DEFAULT 'allow',
  FOREIGN KEY(role_id) REFERENCES roles(role_id)
);
CREATE TABLE IF NOT EXISTS function_definitions (
  code TEXT NOT NULL, version INTEGER NOT NULL, stage TEXT NOT NULL, name TEXT NOT NULL,
  description TEXT NOT NULL, handler TEXT NOT NULL, purpose TEXT NOT NULL,
  parameter_schema_json TEXT NOT NULL, output_classification TEXT NOT NULL,
  lifecycle TEXT NOT NULL CHECK(lifecycle IN ('draft','active','retired')),
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, activated_at TEXT,
  PRIMARY KEY(code,version)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_function
  ON function_definitions(code) WHERE lifecycle='active';
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, mapping_profile_id TEXT NOT NULL,
  mapping_version INTEGER NOT NULL, requested_by TEXT NOT NULL, purpose TEXT NOT NULL,
  status TEXT NOT NULL, report_ids_json TEXT, created_at TEXT NOT NULL,
  started_at TEXT, completed_at TEXT, FOREIGN KEY(source_id) REFERENCES sources(source_id)
);
CREATE TABLE IF NOT EXISTS raw_snapshots (
  snapshot_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, source_id TEXT NOT NULL,
  source_record_id TEXT NOT NULL, payload_json TEXT NOT NULL, content_hash TEXT NOT NULL,
  captured_at TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS function_runs (
  function_run_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, function_code TEXT NOT NULL,
  function_version INTEGER NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL,
  parameters_json TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, error TEXT,
  summary_json TEXT, artifacts_json TEXT, FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS findings (
  finding_id TEXT PRIMARY KEY, function_run_id TEXT NOT NULL, run_id TEXT NOT NULL,
  function_code TEXT NOT NULL, report_id TEXT, entity_id TEXT, jurisdiction TEXT,
  severity TEXT NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL,
  evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(function_run_id) REFERENCES function_runs(function_run_id)
);
CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
  resource TEXT NOT NULL, purpose TEXT, decision TEXT NOT NULL,
  detail_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mapping_dictionary_entries (
  profile_id TEXT NOT NULL, mapping_version INTEGER NOT NULL,
  logical_object TEXT NOT NULL, canonical_field TEXT NOT NULL,
  physical_schema TEXT, physical_table TEXT, physical_column TEXT NOT NULL,
  data_type TEXT, nullable INTEGER NOT NULL DEFAULT 1, description TEXT,
  transform_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(profile_id,mapping_version,logical_object,canonical_field),
  FOREIGN KEY(profile_id,mapping_version) REFERENCES mapping_profiles(profile_id,version)
);
CREATE TABLE IF NOT EXISTS pipeline_profiles (
  profile_id TEXT PRIMARY KEY, name TEXT NOT NULL, route_json TEXT NOT NULL,
  storage_bindings_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lots (
  lot_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, external_lot_ref TEXT,
  status TEXT NOT NULL, report_count INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL, mapping_profile_id TEXT NOT NULL,
  mapping_version INTEGER NOT NULL, received_by TEXT NOT NULL, received_at TEXT NOT NULL,
  FOREIGN KEY(source_id) REFERENCES sources(source_id)
);
CREATE TABLE IF NOT EXISTS datasets (
  dataset_id TEXT NOT NULL, version INTEGER NOT NULL, lot_id TEXT NOT NULL,
  zone TEXT NOT NULL CHECK(zone IN ('landing','canonical','dq_passed','enriched','risk_ready')),
  status TEXT NOT NULL CHECK(status IN ('draft','published','superseded')),
  parent_dataset_id TEXT, parent_version INTEGER, pipeline_profile_id TEXT NOT NULL,
  report_count INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL,
  metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, published_at TEXT,
  PRIMARY KEY(dataset_id,version), FOREIGN KEY(lot_id) REFERENCES lots(lot_id),
  FOREIGN KEY(pipeline_profile_id) REFERENCES pipeline_profiles(profile_id)
);
CREATE TABLE IF NOT EXISTS dataset_lineage (
  lineage_id TEXT PRIMARY KEY, parent_dataset_id TEXT NOT NULL, parent_version INTEGER NOT NULL,
  child_dataset_id TEXT NOT NULL, child_version INTEGER NOT NULL,
  transition TEXT NOT NULL, reason TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_run_inputs (
  run_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL,
  input_zone TEXT NOT NULL, FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(dataset_id,dataset_version) REFERENCES datasets(dataset_id,version)
);
CREATE TABLE IF NOT EXISTS gate_evaluations (
  evaluation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
  dataset_version INTEGER NOT NULL, policy_json TEXT NOT NULL, eligible_count INTEGER NOT NULL,
  rejected_count INTEGER NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS record_dispositions (
  evaluation_id TEXT NOT NULL, report_id TEXT NOT NULL, disposition TEXT NOT NULL,
  blocking_finding_count INTEGER NOT NULL, reason_codes_json TEXT NOT NULL,
  PRIMARY KEY(evaluation_id,report_id), FOREIGN KEY(evaluation_id) REFERENCES gate_evaluations(evaluation_id)
);
CREATE TABLE IF NOT EXISTS promotion_events (
  promotion_id TEXT PRIMARY KEY, source_dataset_id TEXT NOT NULL, source_version INTEGER NOT NULL,
  target_dataset_id TEXT NOT NULL, target_version INTEGER NOT NULL,
  source_zone TEXT NOT NULL, target_zone TEXT NOT NULL, evaluation_id TEXT,
  promoted_count INTEGER NOT NULL, rejected_count INTEGER NOT NULL,
  requested_by TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS enrichment_attributes (
  enrichment_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL,
  report_id TEXT NOT NULL, entity_id TEXT, attribute_name TEXT NOT NULL,
  value_json TEXT NOT NULL, source_ref TEXT NOT NULL, confidence REAL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_results (
  risk_result_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, function_run_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL, report_id TEXT,
  entity_id TEXT, jurisdiction TEXT, rule_code TEXT NOT NULL, severity TEXT,
  result_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_score_components (
  component_id TEXT PRIMARY KEY, risk_result_id TEXT NOT NULL, component_code TEXT NOT NULL,
  score REAL NOT NULL, weight REAL, explanation TEXT,
  FOREIGN KEY(risk_result_id) REFERENCES risk_results(risk_result_id)
);
CREATE TABLE IF NOT EXISTS selection_batches (
  selection_batch_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
  dataset_version INTEGER NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS selection_candidates (
  candidate_id TEXT PRIMARY KEY, selection_batch_id TEXT NOT NULL, report_id TEXT NOT NULL,
  entity_id TEXT, entity_name TEXT, reason_code TEXT NOT NULL, score REAL,
  evidence_json TEXT NOT NULL, decision TEXT NOT NULL DEFAULT 'pending',
  decision_rationale TEXT, decided_by TEXT, decided_at TEXT,
  FOREIGN KEY(selection_batch_id) REFERENCES selection_batches(selection_batch_id)
);
CREATE TABLE IF NOT EXISTS stg_source_records (
  dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL, source_record_id TEXT NOT NULL,
  payload_json TEXT NOT NULL, content_hash TEXT NOT NULL, captured_at TEXT NOT NULL,
  PRIMARY KEY(dataset_id,dataset_version,source_record_id)
);
CREATE TABLE IF NOT EXISTS stg_reports (
  dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL, report_id TEXT NOT NULL,
  message_ref_id TEXT NOT NULL, reporting_entity_id TEXT NOT NULL,
  reporting_entity_name TEXT NOT NULL, reporting_period_end TEXT NOT NULL,
  reporting_currency TEXT, receiving_jurisdiction TEXT NOT NULL,
  PRIMARY KEY(dataset_id,dataset_version,report_id)
);
CREATE TABLE IF NOT EXISTS stg_entities (
  dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL, report_id TEXT NOT NULL,
  entity_id TEXT NOT NULL, name TEXT NOT NULL, tax_jurisdiction TEXT NOT NULL,
  tin TEXT, role TEXT, PRIMARY KEY(dataset_id,dataset_version,report_id,entity_id)
);
CREATE TABLE IF NOT EXISTS stg_metrics (
  dataset_id TEXT NOT NULL, dataset_version INTEGER NOT NULL, report_id TEXT NOT NULL,
  metric_seq INTEGER NOT NULL, jurisdiction TEXT NOT NULL, currency_code TEXT,
  currency_by_measure_json TEXT NOT NULL DEFAULT '{}', revenue TEXT,
  profit_before_tax TEXT, income_tax_paid TEXT, income_tax_accrued TEXT,
  employees INTEGER, tangible_assets TEXT, stated_capital TEXT,
  accumulated_earnings TEXT, unrelated_revenue TEXT, related_revenue TEXT,
  PRIMARY KEY(dataset_id,dataset_version,report_id,metric_seq)
);
CREATE TABLE IF NOT EXISTS can_reports AS SELECT * FROM stg_reports WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_can_reports ON can_reports(dataset_id,dataset_version,report_id);
CREATE TABLE IF NOT EXISTS can_entities AS SELECT * FROM stg_entities WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_can_entities ON can_entities(dataset_id,dataset_version,report_id,entity_id);
CREATE TABLE IF NOT EXISTS can_metrics AS SELECT * FROM stg_metrics WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_can_metrics ON can_metrics(dataset_id,dataset_version,report_id,metric_seq);
CREATE TABLE IF NOT EXISTS dqp_reports AS SELECT * FROM stg_reports WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_dqp_reports ON dqp_reports(dataset_id,dataset_version,report_id);
CREATE TABLE IF NOT EXISTS dqp_entities AS SELECT * FROM stg_entities WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_dqp_entities ON dqp_entities(dataset_id,dataset_version,report_id,entity_id);
CREATE TABLE IF NOT EXISTS dqp_metrics AS SELECT * FROM stg_metrics WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_dqp_metrics ON dqp_metrics(dataset_id,dataset_version,report_id,metric_seq);
CREATE TABLE IF NOT EXISTS enr_reports AS SELECT * FROM stg_reports WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_enr_reports ON enr_reports(dataset_id,dataset_version,report_id);
CREATE TABLE IF NOT EXISTS enr_entities AS SELECT * FROM stg_entities WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_enr_entities ON enr_entities(dataset_id,dataset_version,report_id,entity_id);
CREATE TABLE IF NOT EXISTS enr_metrics AS SELECT * FROM stg_metrics WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_enr_metrics ON enr_metrics(dataset_id,dataset_version,report_id,metric_seq);
CREATE TABLE IF NOT EXISTS rr_reports AS SELECT * FROM stg_reports WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rr_reports ON rr_reports(dataset_id,dataset_version,report_id);
CREATE TABLE IF NOT EXISTS rr_entities AS SELECT * FROM stg_entities WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rr_entities ON rr_entities(dataset_id,dataset_version,report_id,entity_id);
CREATE TABLE IF NOT EXISTS rr_metrics AS SELECT * FROM stg_metrics WHERE 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rr_metrics ON rr_metrics(dataset_id,dataset_version,report_id,metric_seq);
DROP TRIGGER IF EXISTS immutable_stg_source_records_update;
DROP TRIGGER IF EXISTS immutable_stg_source_records_delete;
CREATE TRIGGER immutable_stg_source_records_update BEFORE UPDATE ON stg_source_records
BEGIN SELECT RAISE(ABORT,'landing source records are immutable'); END;
CREATE TRIGGER immutable_stg_source_records_delete BEFORE DELETE ON stg_source_records
BEGIN SELECT RAISE(ABORT,'landing source records are immutable'); END;
DROP TRIGGER IF EXISTS immutable_stg_reports_update;
DROP TRIGGER IF EXISTS immutable_stg_reports_delete;
CREATE TRIGGER immutable_stg_reports_update BEFORE UPDATE ON stg_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_stg_reports_delete BEFORE DELETE ON stg_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_stg_entities_update;
DROP TRIGGER IF EXISTS immutable_stg_entities_delete;
CREATE TRIGGER immutable_stg_entities_update BEFORE UPDATE ON stg_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_stg_entities_delete BEFORE DELETE ON stg_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_stg_metrics_update;
DROP TRIGGER IF EXISTS immutable_stg_metrics_delete;
CREATE TRIGGER immutable_stg_metrics_update BEFORE UPDATE ON stg_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_stg_metrics_delete BEFORE DELETE ON stg_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_can_reports_update;
DROP TRIGGER IF EXISTS immutable_can_reports_delete;
CREATE TRIGGER immutable_can_reports_update BEFORE UPDATE ON can_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_can_reports_delete BEFORE DELETE ON can_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_can_entities_update;
DROP TRIGGER IF EXISTS immutable_can_entities_delete;
CREATE TRIGGER immutable_can_entities_update BEFORE UPDATE ON can_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_can_entities_delete BEFORE DELETE ON can_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_can_metrics_update;
DROP TRIGGER IF EXISTS immutable_can_metrics_delete;
CREATE TRIGGER immutable_can_metrics_update BEFORE UPDATE ON can_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_can_metrics_delete BEFORE DELETE ON can_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_dqp_reports_update;
DROP TRIGGER IF EXISTS immutable_dqp_reports_delete;
CREATE TRIGGER immutable_dqp_reports_update BEFORE UPDATE ON dqp_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_dqp_reports_delete BEFORE DELETE ON dqp_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_dqp_entities_update;
DROP TRIGGER IF EXISTS immutable_dqp_entities_delete;
CREATE TRIGGER immutable_dqp_entities_update BEFORE UPDATE ON dqp_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_dqp_entities_delete BEFORE DELETE ON dqp_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_dqp_metrics_update;
DROP TRIGGER IF EXISTS immutable_dqp_metrics_delete;
CREATE TRIGGER immutable_dqp_metrics_update BEFORE UPDATE ON dqp_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_dqp_metrics_delete BEFORE DELETE ON dqp_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_enr_reports_update;
DROP TRIGGER IF EXISTS immutable_enr_reports_delete;
CREATE TRIGGER immutable_enr_reports_update BEFORE UPDATE ON enr_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_enr_reports_delete BEFORE DELETE ON enr_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_enr_entities_update;
DROP TRIGGER IF EXISTS immutable_enr_entities_delete;
CREATE TRIGGER immutable_enr_entities_update BEFORE UPDATE ON enr_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_enr_entities_delete BEFORE DELETE ON enr_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_enr_metrics_update;
DROP TRIGGER IF EXISTS immutable_enr_metrics_delete;
CREATE TRIGGER immutable_enr_metrics_update BEFORE UPDATE ON enr_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_enr_metrics_delete BEFORE DELETE ON enr_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_rr_reports_update;
DROP TRIGGER IF EXISTS immutable_rr_reports_delete;
CREATE TRIGGER immutable_rr_reports_update BEFORE UPDATE ON rr_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_rr_reports_delete BEFORE DELETE ON rr_reports
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_rr_entities_update;
DROP TRIGGER IF EXISTS immutable_rr_entities_delete;
CREATE TRIGGER immutable_rr_entities_update BEFORE UPDATE ON rr_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_rr_entities_delete BEFORE DELETE ON rr_entities
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_rr_metrics_update;
DROP TRIGGER IF EXISTS immutable_rr_metrics_delete;
CREATE TRIGGER immutable_rr_metrics_update BEFORE UPDATE ON rr_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
CREATE TRIGGER immutable_rr_metrics_delete BEFORE DELETE ON rr_metrics
BEGIN SELECT RAISE(ABORT,'published zone rows are immutable'); END;
DROP TRIGGER IF EXISTS immutable_raw_update;
DROP TRIGGER IF EXISTS immutable_raw_delete;
DROP TRIGGER IF EXISTS immutable_active_function_update;
DROP TRIGGER IF EXISTS immutable_active_mapping_update;
CREATE TRIGGER immutable_raw_update
BEFORE UPDATE ON raw_snapshots BEGIN SELECT RAISE(ABORT,'raw snapshots are immutable'); END;
CREATE TRIGGER immutable_raw_delete
BEFORE DELETE ON raw_snapshots BEGIN SELECT RAISE(ABORT,'raw snapshots are immutable'); END;
CREATE TRIGGER immutable_active_function_update
BEFORE UPDATE ON function_definitions WHEN OLD.lifecycle='active' AND NOT (
  NEW.lifecycle='retired' AND NEW.code=OLD.code AND NEW.version=OLD.version
  AND NEW.stage=OLD.stage AND NEW.name=OLD.name AND NEW.description=OLD.description
  AND NEW.handler=OLD.handler AND NEW.purpose=OLD.purpose
  AND NEW.parameter_schema_json=OLD.parameter_schema_json
  AND NEW.output_classification=OLD.output_classification
)
BEGIN SELECT RAISE(ABORT,'active function versions are immutable'); END;
CREATE TRIGGER immutable_active_mapping_update
BEFORE UPDATE ON mapping_profiles WHEN OLD.lifecycle='active' AND NOT (
  NEW.lifecycle='retired' AND NEW.profile_id=OLD.profile_id
  AND NEW.source_id=OLD.source_id AND NEW.version=OLD.version
  AND NEW.mapping_json=OLD.mapping_json
)
BEGIN SELECT RAISE(ABORT,'active mapping versions are immutable'); END;
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialise(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            for table in ("stg_metrics", "can_metrics", "dqp_metrics", "enr_metrics", "rr_metrics"):
                columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                if "currency_code" not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN currency_code TEXT")
                if "currency_by_measure_json" not in columns:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN currency_by_measure_json TEXT NOT NULL DEFAULT '{{}}'"
                    )

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.connect() as connection:
            connection.execute(sql, params)

    def execute_many(self, sql: str, params: list[tuple[Any, ...]]) -> None:
        with self.connect() as connection:
            connection.executemany(sql, params)

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def audit(
        self, event_id: str, actor: str, action: str, resource: str,
        decision: str, purpose: str | None = None, detail: dict[str, Any] | None = None,
    ) -> None:
        self.execute(
            "INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?)",
            (event_id, actor, action, resource, purpose, decision,
             json.dumps(detail or {}, sort_keys=True), utc_now()),
        )
