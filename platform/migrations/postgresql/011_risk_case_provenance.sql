\set ON_ERROR_STOP on
BEGIN;

CREATE TABLE IF NOT EXISTS cbcr_risk.result_set (
  result_set_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id uuid NOT NULL,
  dataset_version integer NOT NULL,
  name varchar(200) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'draft',
  selection_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  approved_by text,
  approved_at timestamptz,
  CONSTRAINT fk_risk_result_set_dataset
    FOREIGN KEY(dataset_id,dataset_version)
    REFERENCES cbcr_control.dataset(dataset_id,version),
  CONSTRAINT ck_risk_result_set_status
    CHECK(status IN ('draft','approved','superseded'))
);

CREATE TABLE IF NOT EXISTS cbcr_risk.result_set_run (
  result_set_id uuid NOT NULL REFERENCES cbcr_risk.result_set(result_set_id) ON DELETE CASCADE,
  run_id uuid NOT NULL REFERENCES cbcr_control.run(run_id),
  PRIMARY KEY(result_set_id,run_id)
);

ALTER TABLE cbcr_selection.selection_batch
  ADD COLUMN IF NOT EXISTS risk_result_set_id uuid REFERENCES cbcr_risk.result_set(result_set_id),
  ADD COLUMN IF NOT EXISTS selection_policy jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS cbcr_selection.candidate_source_result (
  candidate_id uuid NOT NULL REFERENCES cbcr_selection.candidate(candidate_id) ON DELETE CASCADE,
  risk_result_id uuid NOT NULL REFERENCES cbcr_risk.result(risk_result_id),
  PRIMARY KEY(candidate_id,risk_result_id)
);

CREATE TABLE IF NOT EXISTS cbcr_selection.case_set (
  case_set_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  selection_batch_id uuid NOT NULL REFERENCES cbcr_selection.selection_batch(selection_batch_id),
  version integer NOT NULL,
  name varchar(200) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'finalized',
  selected_count integer NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  finalized_by text NOT NULL,
  finalized_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_case_set_version UNIQUE(selection_batch_id,version),
  CONSTRAINT ck_case_set_status CHECK(status IN ('finalized','exported','superseded'))
);

CREATE TABLE IF NOT EXISTS cbcr_selection.case_set_item (
  case_set_id uuid NOT NULL REFERENCES cbcr_selection.case_set(case_set_id) ON DELETE CASCADE,
  candidate_id uuid NOT NULL REFERENCES cbcr_selection.candidate(candidate_id),
  PRIMARY KEY(case_set_id,candidate_id)
);

CREATE TABLE IF NOT EXISTS cbcr_selection.audit_case (
  audit_case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_set_id uuid NOT NULL REFERENCES cbcr_selection.case_set(case_set_id),
  candidate_id uuid NOT NULL REFERENCES cbcr_selection.candidate(candidate_id),
  dataset_id uuid NOT NULL,
  dataset_version integer NOT NULL,
  report_id varchar(200) NOT NULL,
  entity_id varchar(200),
  status varchar(30) NOT NULL DEFAULT 'ready_for_handoff',
  external_reference text,
  case_snapshot jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_audit_case_version UNIQUE(case_set_id,candidate_id),
  CONSTRAINT fk_audit_case_dataset
    FOREIGN KEY(dataset_id,dataset_version)
    REFERENCES cbcr_control.dataset(dataset_id,version),
  CONSTRAINT ck_audit_case_status CHECK(status IN (
    'ready_for_handoff','exported','accepted_by_audit','closed'
  ))
);

CREATE TABLE IF NOT EXISTS cbcr_selection.audit_case_event (
  audit_case_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  audit_case_id uuid NOT NULL REFERENCES cbcr_selection.audit_case(audit_case_id) ON DELETE CASCADE,
  event_type varchar(60) NOT NULL,
  previous_status varchar(30),
  status varchar(30) NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  actor text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_risk_result_set_dataset
  ON cbcr_risk.result_set(dataset_id,dataset_version,status);
CREATE INDEX IF NOT EXISTS idx_result_set_run_run
  ON cbcr_risk.result_set_run(run_id);
CREATE INDEX IF NOT EXISTS idx_selection_batch_risk_set
  ON cbcr_selection.selection_batch(risk_result_set_id);
CREATE INDEX IF NOT EXISTS idx_candidate_source_result_result
  ON cbcr_selection.candidate_source_result(risk_result_id);
CREATE INDEX IF NOT EXISTS idx_audit_case_status
  ON cbcr_selection.audit_case(status,created_at);

GRANT SELECT,INSERT,UPDATE ON cbcr_risk.result_set,cbcr_risk.result_set_run,
  cbcr_selection.candidate_source_result,cbcr_selection.case_set,
  cbcr_selection.case_set_item,cbcr_selection.audit_case,
  cbcr_selection.audit_case_event TO cbcr_user;

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES (
  '011_risk_case_provenance',
  'Add approved risk-result sets, candidate provenance, finalized case sets and audit handoff records'
)
ON CONFLICT(migration_id) DO NOTHING;

COMMIT;
