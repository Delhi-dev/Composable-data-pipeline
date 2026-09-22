\set ON_ERROR_STOP on
BEGIN;

-- Generic immutable raw-source snapshots for fixture/API/database sources. Original XML
-- continues to live in cbcr_staging.xml_document; this table preserves the exact record
-- envelope consumed by the canonical mapper.
CREATE TABLE IF NOT EXISTS cbcr_staging.source_record (
  dataset_id uuid NOT NULL,
  dataset_version integer NOT NULL,
  source_record_id text NOT NULL,
  payload jsonb NOT NULL,
  content_hash text NOT NULL,
  captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(dataset_id,dataset_version,source_record_id),
  FOREIGN KEY(dataset_id,dataset_version)
    REFERENCES cbcr_control.dataset(dataset_id,version)
);

DROP TRIGGER IF EXISTS immutable_source_record ON cbcr_staging.source_record;
CREATE TRIGGER immutable_source_record BEFORE UPDATE OR DELETE ON cbcr_staging.source_record
FOR EACH ROW EXECUTE FUNCTION cbcr_control.reject_published_mutation();

-- Runtime output and worker coordination fields required by the PostgreSQL API/worker.
ALTER TABLE cbcr_control.function_run
  ADD COLUMN IF NOT EXISTS artifacts jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS claimed_by text,
  ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS next_attempt_at timestamptz,
  ADD COLUMN IF NOT EXISTS maximum_attempts integer NOT NULL DEFAULT 3;

ALTER TABLE cbcr_control.run
  ADD COLUMN IF NOT EXISTS report_ids jsonb;

ALTER TABLE cbcr_dq.finding
  ADD COLUMN IF NOT EXISTS function_run_id uuid,
  ADD COLUMN IF NOT EXISTS dedup_key text;

ALTER TABLE cbcr_dq.finding DROP CONSTRAINT IF EXISTS fk_finding_function_run;
ALTER TABLE cbcr_dq.finding ADD CONSTRAINT fk_finding_function_run
  FOREIGN KEY(function_run_id) REFERENCES cbcr_control.function_run(function_run_id);

ALTER TABLE cbcr_risk.result
  ADD COLUMN IF NOT EXISTS function_run_id uuid,
  ADD COLUMN IF NOT EXISTS output_key text;

ALTER TABLE cbcr_risk.result DROP CONSTRAINT IF EXISTS fk_risk_function_run;
ALTER TABLE cbcr_risk.result ADD CONSTRAINT fk_risk_function_run
  FOREIGN KEY(function_run_id) REFERENCES cbcr_control.function_run(function_run_id);

CREATE INDEX IF NOT EXISTS idx_pg_run_status_created
  ON cbcr_control.run(status,created_at);
CREATE INDEX IF NOT EXISTS idx_pg_function_run_parent
  ON cbcr_control.function_run(run_id,stage,function_code);
CREATE INDEX IF NOT EXISTS idx_pg_function_run_lease
  ON cbcr_control.function_run(status,lease_expires_at)
  WHERE status='running';
CREATE INDEX IF NOT EXISTS idx_pg_dataset_lot_zone
  ON cbcr_control.dataset(lot_id,zone,created_at);
CREATE INDEX IF NOT EXISTS idx_pg_lineage_parent
  ON cbcr_control.dataset_lineage(parent_dataset_id,parent_version,created_at);
CREATE INDEX IF NOT EXISTS idx_pg_lineage_child
  ON cbcr_control.dataset_lineage(child_dataset_id,child_version,created_at);
CREATE INDEX IF NOT EXISTS idx_pg_finding_run_report
  ON cbcr_dq.finding(run_id,report_id,severity,created_at);
CREATE INDEX IF NOT EXISTS idx_pg_risk_dataset_run_report
  ON cbcr_risk.result(dataset_id,dataset_version,run_id,report_id,created_at);
CREATE INDEX IF NOT EXISTS idx_pg_audit_time_actor
  ON cbcr_control.audit_event(created_at DESC,actor);

CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_finding_dedup
  ON cbcr_dq.finding(function_run_id,dedup_key)
  WHERE function_run_id IS NOT NULL AND dedup_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_risk_output
  ON cbcr_risk.result(function_run_id,output_key)
  WHERE function_run_id IS NOT NULL AND output_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_selection_batch_run
  ON cbcr_selection.selection_batch(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_candidate_logical
  ON cbcr_selection.candidate(
    selection_batch_id,report_id,COALESCE(entity_id,''),reason_code
  );
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_promotion_logical
  ON cbcr_dq.promotion_event(
    source_dataset_id,source_version,target_zone,COALESCE(evaluation_id,'00000000-0000-0000-0000-000000000000'::uuid)
  );

ALTER TABLE cbcr_control.function_run DROP CONSTRAINT IF EXISTS ck_function_run_attempts;
ALTER TABLE cbcr_control.function_run ADD CONSTRAINT ck_function_run_attempts
  CHECK(attempt >= 0 AND maximum_attempts >= 1 AND attempt <= maximum_attempts);

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES ('004_postgresql_runtime_alignment',
        'Add artifacts, function provenance, worker leases and idempotency controls')
ON CONFLICT(migration_id) DO NOTHING;

COMMIT;
