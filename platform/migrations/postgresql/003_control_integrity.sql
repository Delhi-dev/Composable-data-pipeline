\set ON_ERROR_STOP on
BEGIN;

-- Database-resident catalogue and independent asynchronous work items.
CREATE TABLE IF NOT EXISTS cbcr_control.function_definition (
  function_code varchar(100) NOT NULL,
  version integer NOT NULL,
  stage char(2) NOT NULL,
  name text NOT NULL,
  description text NOT NULL,
  handler text NOT NULL,
  purpose varchar(40) NOT NULL,
  parameter_schema jsonb NOT NULL DEFAULT '{}'::jsonb,
  output_classification varchar(30) NOT NULL DEFAULT 'restricted',
  lifecycle varchar(20) NOT NULL DEFAULT 'draft',
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  activated_at timestamptz,
  retired_at timestamptz,
  PRIMARY KEY(function_code,version),
  CONSTRAINT ck_function_stage CHECK(stage IN ('01','02','03','04','05','06','07')),
  CONSTRAINT ck_function_lifecycle CHECK(lifecycle IN ('draft','active','retired'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_active_function
  ON cbcr_control.function_definition(function_code) WHERE lifecycle='active';

CREATE TABLE IF NOT EXISTS cbcr_control.function_run (
  function_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES cbcr_control.run(run_id),
  function_code varchar(100) NOT NULL,
  function_version integer NOT NULL,
  stage char(2) NOT NULL,
  status varchar(30) NOT NULL DEFAULT 'queued',
  parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
  attempt integer NOT NULL DEFAULT 0,
  queued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  started_at timestamptz,
  completed_at timestamptz,
  result_summary jsonb,
  error jsonb,
  FOREIGN KEY(function_code,function_version)
    REFERENCES cbcr_control.function_definition(function_code,version),
  CONSTRAINT ck_function_run_status CHECK
    (status IN ('queued','running','succeeded','failed','cancelled')),
  UNIQUE(run_id,function_code,function_version)
);
CREATE INDEX IF NOT EXISTS idx_function_run_queue
  ON cbcr_control.function_run(status,queued_at);

-- The user-accessibility module is separate from stage functions. Permissions from all
-- roles are unioned; a deny can override an allow in the application policy evaluator.
CREATE TABLE IF NOT EXISTS cbcr_control.user_account (
  user_id varchar(200) PRIMARY KEY,
  display_name text NOT NULL,
  external_subject text UNIQUE,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_control.role (
  role_id varchar(100) PRIMARY KEY,
  name text NOT NULL,
  description text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_control.user_role (
  user_id varchar(200) NOT NULL REFERENCES cbcr_control.user_account(user_id),
  role_id varchar(100) NOT NULL REFERENCES cbcr_control.role(role_id),
  assigned_by text NOT NULL,
  assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(user_id,role_id)
);
CREATE TABLE IF NOT EXISTS cbcr_control.role_permission (
  permission_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  role_id varchar(100) NOT NULL REFERENCES cbcr_control.role(role_id),
  action varchar(100) NOT NULL,
  stage char(2),
  purpose varchar(40),
  effect varchar(10) NOT NULL DEFAULT 'allow',
  CONSTRAINT ck_role_permission_effect CHECK(effect IN ('allow','deny')),
  UNIQUE(role_id,action,stage,purpose)
);

-- Complete dataset and mapping lineage at the database level.
ALTER TABLE cbcr_control.lot DROP CONSTRAINT IF EXISTS fk_lot_mapping_profile;
ALTER TABLE cbcr_control.lot ADD CONSTRAINT fk_lot_mapping_profile
  FOREIGN KEY(mapping_profile_id,mapping_version)
  REFERENCES cbcr_control.mapping_profile(profile_id,version);
ALTER TABLE cbcr_control.dataset DROP CONSTRAINT IF EXISTS fk_dataset_parent;
ALTER TABLE cbcr_control.dataset ADD CONSTRAINT fk_dataset_parent
  FOREIGN KEY(parent_dataset_id,parent_version)
  REFERENCES cbcr_control.dataset(dataset_id,version);
ALTER TABLE cbcr_control.dataset_lineage DROP CONSTRAINT IF EXISTS fk_lineage_parent;
ALTER TABLE cbcr_control.dataset_lineage ADD CONSTRAINT fk_lineage_parent
  FOREIGN KEY(parent_dataset_id,parent_version)
  REFERENCES cbcr_control.dataset(dataset_id,version);
ALTER TABLE cbcr_control.dataset_lineage DROP CONSTRAINT IF EXISTS fk_lineage_child;
ALTER TABLE cbcr_control.dataset_lineage ADD CONSTRAINT fk_lineage_child
  FOREIGN KEY(child_dataset_id,child_version)
  REFERENCES cbcr_control.dataset(dataset_id,version);

ALTER TABLE cbcr_dq.gate_evaluation DROP CONSTRAINT IF EXISTS fk_gate_dataset;
ALTER TABLE cbcr_dq.gate_evaluation ADD CONSTRAINT fk_gate_dataset
  FOREIGN KEY(dataset_id,dataset_version) REFERENCES cbcr_control.dataset(dataset_id,version);
ALTER TABLE cbcr_dq.promotion_event DROP CONSTRAINT IF EXISTS fk_promotion_source_dataset;
ALTER TABLE cbcr_dq.promotion_event ADD CONSTRAINT fk_promotion_source_dataset
  FOREIGN KEY(source_dataset_id,source_version) REFERENCES cbcr_control.dataset(dataset_id,version);
ALTER TABLE cbcr_dq.promotion_event DROP CONSTRAINT IF EXISTS fk_promotion_target_dataset;
ALTER TABLE cbcr_dq.promotion_event ADD CONSTRAINT fk_promotion_target_dataset
  FOREIGN KEY(target_dataset_id,target_version) REFERENCES cbcr_control.dataset(dataset_id,version);
ALTER TABLE cbcr_enriched.attribute DROP CONSTRAINT IF EXISTS fk_enrichment_dataset;
ALTER TABLE cbcr_enriched.attribute ADD CONSTRAINT fk_enrichment_dataset
  FOREIGN KEY(dataset_id,dataset_version) REFERENCES cbcr_control.dataset(dataset_id,version);
ALTER TABLE cbcr_risk.result DROP CONSTRAINT IF EXISTS fk_risk_result_dataset;
ALTER TABLE cbcr_risk.result ADD CONSTRAINT fk_risk_result_dataset
  FOREIGN KEY(dataset_id,dataset_version) REFERENCES cbcr_control.dataset(dataset_id,version);
ALTER TABLE cbcr_selection.selection_batch DROP CONSTRAINT IF EXISTS fk_selection_dataset;
ALTER TABLE cbcr_selection.selection_batch ADD CONSTRAINT fk_selection_dataset
  FOREIGN KEY(dataset_id,dataset_version) REFERENCES cbcr_control.dataset(dataset_id,version);

-- Each stable business row belongs to a registered dataset version. Child-to-report FKs
-- enforce that entities and metrics cannot drift away from their report.
DO $migration$
DECLARE zone text;
BEGIN
  FOREACH zone IN ARRAY ARRAY['cbcr_canonical','cbcr_dq_published','cbcr_enriched','cbcr_risk_ready']
  LOOP
    EXECUTE format('ALTER TABLE %I.report DROP CONSTRAINT IF EXISTS fk_%s_report_dataset',zone,zone);
    EXECUTE format('ALTER TABLE %I.report ADD CONSTRAINT fk_%s_report_dataset FOREIGN KEY(dataset_id,dataset_version) REFERENCES cbcr_control.dataset(dataset_id,version)',zone,zone);
    EXECUTE format('ALTER TABLE %I.entity DROP CONSTRAINT IF EXISTS fk_%s_entity_report',zone,zone);
    EXECUTE format('ALTER TABLE %I.entity ADD CONSTRAINT fk_%s_entity_report FOREIGN KEY(dataset_id,dataset_version,report_id) REFERENCES %I.report(dataset_id,dataset_version,report_id)',zone,zone,zone);
    EXECUTE format('ALTER TABLE %I.jurisdiction_metric DROP CONSTRAINT IF EXISTS fk_%s_metric_report',zone,zone);
    EXECUTE format('ALTER TABLE %I.jurisdiction_metric ADD CONSTRAINT fk_%s_metric_report FOREIGN KEY(dataset_id,dataset_version,report_id) REFERENCES %I.report(dataset_id,dataset_version,report_id)',zone,zone,zone);
  END LOOP;
END
$migration$;

-- Published business rows are append-only. Corrections create a new dataset version.
CREATE OR REPLACE FUNCTION cbcr_control.reject_published_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'published CbCR rows are immutable; create a new dataset version';
END
$$;
DO $migration$
DECLARE zone text; object_name text; trigger_name text;
BEGIN
  FOREACH zone IN ARRAY ARRAY['cbcr_canonical','cbcr_dq_published','cbcr_enriched','cbcr_risk_ready']
  LOOP
    FOREACH object_name IN ARRAY ARRAY['report','entity','jurisdiction_metric']
    LOOP
      trigger_name := 'immutable_' || replace(zone,'cbcr_','') || '_' || object_name;
      EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I.%I',trigger_name,zone,object_name);
      EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I.%I FOR EACH ROW EXECUTE FUNCTION cbcr_control.reject_published_mutation()',trigger_name,zone,object_name);
    END LOOP;
  END LOOP;
END
$migration$;

-- The raw XML itself is immutable while parser status metadata may progress.
CREATE OR REPLACE FUNCTION cbcr_control.protect_xml_payload()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.xml_payload IS DISTINCT FROM NEW.xml_payload
     OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256 THEN
    RAISE EXCEPTION 'landed XML payload and hash are immutable';
  END IF;
  RETURN NEW;
END
$$;
DROP TRIGGER IF EXISTS immutable_xml_payload ON cbcr_staging.xml_document;
CREATE TRIGGER immutable_xml_payload BEFORE UPDATE ON cbcr_staging.xml_document
FOR EACH ROW EXECUTE FUNCTION cbcr_control.protect_xml_payload();

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES ('003_control_integrity','Add function queue, RBAC, lineage FKs and database immutability')
ON CONFLICT(migration_id) DO NOTHING;

COMMIT;
