\set ON_ERROR_STOP on
BEGIN;

-- Migration ledger. Existing XML-consumption tables are extended, never replaced.
CREATE SCHEMA IF NOT EXISTS cbcr_control;
CREATE TABLE IF NOT EXISTS cbcr_control.schema_migration (
  migration_id varchar(100) PRIMARY KEY,
  description text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Raw XML and parser evidence belong in a dedicated landing schema.
CREATE SCHEMA IF NOT EXISTS cbcr_staging;
CREATE TABLE IF NOT EXISTS cbcr_staging.xml_document (
  xml_document_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_file_name varchar(500),
  source_uri text,
  content_sha256 char(64) NOT NULL UNIQUE,
  xml_schema_version varchar(20) NOT NULL DEFAULT '2.0',
  xml_payload xml NOT NULL,
  received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  parse_status varchar(30) NOT NULL DEFAULT 'received',
  parser_version varchar(100),
  parsed_at timestamptz,
  CONSTRAINT ck_xml_document_parse_status CHECK
    (parse_status IN ('received','schema_valid','schema_invalid','parsed','parse_failed'))
);
CREATE TABLE IF NOT EXISTS cbcr_staging.xml_validation_issue (
  validation_issue_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  xml_document_id bigint NOT NULL REFERENCES cbcr_staging.xml_document(xml_document_id) ON DELETE CASCADE,
  severity varchar(20) NOT NULL,
  issue_code varchar(100) NOT NULL,
  xpath text,
  line_number integer,
  column_number integer,
  message text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT ck_xml_validation_severity CHECK (severity IN ('info','warning','error','fatal'))
);

-- CbcBody is unbounded in v2.0. The original tables linked directly to MessageSpec,
-- which cannot distinguish multiple bodies in one document.
CREATE TABLE IF NOT EXISTS public.cbcr_body (
  cbc_body_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_spec_id integer NOT NULL REFERENCES public.cbcr_message_spec(message_spec_id) ON DELETE CASCADE,
  body_ordinal integer NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (message_spec_id, body_ordinal)
);
ALTER TABLE public.cbcr_message_spec ADD COLUMN IF NOT EXISTS xml_document_id bigint;
ALTER TABLE public.cbcr_message_spec ADD COLUMN IF NOT EXISTS warning text;
ALTER TABLE public.cbcr_message_spec ADD COLUMN IF NOT EXISTS contact text;
ALTER TABLE public.cbcr_message_spec
  DROP CONSTRAINT IF EXISTS cbcr_message_spec_xml_document_id_fkey;
ALTER TABLE public.cbcr_message_spec
  ADD CONSTRAINT cbcr_message_spec_xml_document_id_fkey FOREIGN KEY (xml_document_id)
  REFERENCES cbcr_staging.xml_document(xml_document_id);
CREATE INDEX IF NOT EXISTS idx_cbcr_message_xml_document ON public.cbcr_message_spec(xml_document_id);

ALTER TABLE public.cbcr_reporting_entity ADD COLUMN IF NOT EXISTS cbc_body_id bigint;
ALTER TABLE public.cbcr_cbcreport ADD COLUMN IF NOT EXISTS cbc_body_id bigint;
ALTER TABLE public.cbcr_additional_info ADD COLUMN IF NOT EXISTS cbc_body_id bigint;
ALTER TABLE public.cbcr_reporting_entity DROP CONSTRAINT IF EXISTS cbcr_reporting_entity_cbc_body_id_fkey;
ALTER TABLE public.cbcr_reporting_entity ADD CONSTRAINT cbcr_reporting_entity_cbc_body_id_fkey
  FOREIGN KEY (cbc_body_id) REFERENCES public.cbcr_body(cbc_body_id) ON DELETE CASCADE;
ALTER TABLE public.cbcr_cbcreport DROP CONSTRAINT IF EXISTS cbcr_cbcreport_cbc_body_id_fkey;
ALTER TABLE public.cbcr_cbcreport ADD CONSTRAINT cbcr_cbcreport_cbc_body_id_fkey
  FOREIGN KEY (cbc_body_id) REFERENCES public.cbcr_body(cbc_body_id) ON DELETE CASCADE;
ALTER TABLE public.cbcr_additional_info DROP CONSTRAINT IF EXISTS cbcr_additional_info_cbc_body_id_fkey;
ALTER TABLE public.cbcr_additional_info ADD CONSTRAINT cbcr_additional_info_cbc_body_id_fkey
  FOREIGN KEY (cbc_body_id) REFERENCES public.cbcr_body(cbc_body_id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_cbcr_reporting_body ON public.cbcr_reporting_entity(cbc_body_id);
CREATE INDEX IF NOT EXISTS idx_cbcr_report_body ON public.cbcr_cbcreport(cbc_body_id);
CREATE INDEX IF NOT EXISTS idx_cbcr_additional_body ON public.cbcr_additional_info(cbc_body_id);

-- Repeatable MessageSpec elements.
CREATE TABLE IF NOT EXISTS public.cbcr_message_receiving_country (
  message_spec_id integer NOT NULL REFERENCES public.cbcr_message_spec(message_spec_id) ON DELETE CASCADE,
  country_ordinal integer NOT NULL,
  country_code char(2) NOT NULL,
  PRIMARY KEY (message_spec_id, country_ordinal)
);
CREATE TABLE IF NOT EXISTS public.cbcr_message_correction_ref (
  message_spec_id integer NOT NULL REFERENCES public.cbcr_message_spec(message_spec_id) ON DELETE CASCADE,
  correction_ordinal integer NOT NULL,
  corr_message_ref_id varchar(170) NOT NULL,
  PRIMARY KEY (message_spec_id, correction_ordinal)
);
CREATE INDEX IF NOT EXISTS idx_cbcr_corr_message_ref ON public.cbcr_message_correction_ref(corr_message_ref_id);

-- Correctable DocSpec allows repeatable CorrDocRefId in the imported STF schema.
CREATE TABLE IF NOT EXISTS public.cbcr_document_correction_ref (
  document_correction_ref_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  document_type varchar(30) NOT NULL,
  reporting_entity_id integer REFERENCES public.cbcr_reporting_entity(reporting_entity_id) ON DELETE CASCADE,
  cbcreport_id integer REFERENCES public.cbcr_cbcreport(cbcreport_id) ON DELETE CASCADE,
  additional_info_id integer REFERENCES public.cbcr_additional_info(additional_info_id) ON DELETE CASCADE,
  correction_ordinal integer NOT NULL,
  corr_doc_ref_id varchar(200) NOT NULL,
  CONSTRAINT ck_document_owner_exactly_one CHECK (
    ((reporting_entity_id IS NOT NULL)::integer + (cbcreport_id IS NOT NULL)::integer +
     (additional_info_id IS NOT NULL)::integer) = 1
  ),
  CONSTRAINT ck_document_type CHECK
    (document_type IN ('reporting_entity','cbc_report','additional_info'))
);
CREATE INDEX IF NOT EXISTS idx_cbcr_corr_doc_ref ON public.cbcr_document_correction_ref(corr_doc_ref_id);

-- Lossless organisation-party cardinalities for reporting and constituent entities.
CREATE TABLE IF NOT EXISTS public.cbcr_organisation_residence (
  organisation_residence_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  organisation_type varchar(30) NOT NULL,
  reporting_entity_id integer REFERENCES public.cbcr_reporting_entity(reporting_entity_id) ON DELETE CASCADE,
  const_entity_id integer REFERENCES public.cbcr_const_entity(const_entity_id) ON DELETE CASCADE,
  residence_ordinal integer NOT NULL,
  country_code char(2) NOT NULL,
  CONSTRAINT ck_org_residence_owner CHECK
    (((reporting_entity_id IS NOT NULL)::integer + (const_entity_id IS NOT NULL)::integer) = 1),
  CONSTRAINT ck_org_residence_type CHECK
    (organisation_type IN ('reporting_entity','constituent_entity'))
);
CREATE TABLE IF NOT EXISTS public.cbcr_organisation_identifier (
  organisation_identifier_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  organisation_type varchar(30) NOT NULL,
  reporting_entity_id integer REFERENCES public.cbcr_reporting_entity(reporting_entity_id) ON DELETE CASCADE,
  const_entity_id integer REFERENCES public.cbcr_const_entity(const_entity_id) ON DELETE CASCADE,
  identifier_ordinal integer NOT NULL,
  identifier_value varchar(200) NOT NULL,
  issued_by char(2),
  identifier_type varchar(200),
  CONSTRAINT ck_org_identifier_owner CHECK
    (((reporting_entity_id IS NOT NULL)::integer + (const_entity_id IS NOT NULL)::integer) = 1),
  CONSTRAINT ck_org_identifier_type CHECK
    (organisation_type IN ('reporting_entity','constituent_entity'))
);
CREATE TABLE IF NOT EXISTS public.cbcr_organisation_name (
  organisation_name_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  organisation_type varchar(30) NOT NULL,
  reporting_entity_id integer REFERENCES public.cbcr_reporting_entity(reporting_entity_id) ON DELETE CASCADE,
  const_entity_id integer REFERENCES public.cbcr_const_entity(const_entity_id) ON DELETE CASCADE,
  name_ordinal integer NOT NULL,
  organisation_name varchar(200) NOT NULL,
  CONSTRAINT ck_org_name_owner CHECK
    (((reporting_entity_id IS NOT NULL)::integer + (const_entity_id IS NOT NULL)::integer) = 1),
  CONSTRAINT ck_org_name_type CHECK
    (organisation_type IN ('reporting_entity','constituent_entity'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_residence_reporting ON public.cbcr_organisation_residence(reporting_entity_id,residence_ordinal) WHERE reporting_entity_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_residence_constituent ON public.cbcr_organisation_residence(const_entity_id,residence_ordinal) WHERE const_entity_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_identifier_reporting ON public.cbcr_organisation_identifier(reporting_entity_id,identifier_ordinal) WHERE reporting_entity_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_identifier_constituent ON public.cbcr_organisation_identifier(const_entity_id,identifier_ordinal) WHERE const_entity_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_name_reporting ON public.cbcr_organisation_name(reporting_entity_id,name_ordinal) WHERE reporting_entity_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_org_name_constituent ON public.cbcr_organisation_name(const_entity_id,name_ordinal) WHERE const_entity_id IS NOT NULL;

-- AddressFix and legalAddressType were absent from both existing address tables.
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS address_ordinal integer;
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS legal_address_type varchar(30);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS street varchar(200);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS building_identifier varchar(200);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS suite_identifier varchar(200);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS floor_identifier varchar(200);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS district_name varchar(200);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS pob varchar(200);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS post_code varchar(200);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS city varchar(200);
ALTER TABLE public.cbcr_entity_address ADD COLUMN IF NOT EXISTS country_subentity varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS address_ordinal integer;
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS legal_address_type varchar(30);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS street varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS building_identifier varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS suite_identifier varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS floor_identifier varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS district_name varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS pob varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS post_code varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS city varchar(200);
ALTER TABLE public.cbcr_const_entity_address ADD COLUMN IF NOT EXISTS country_subentity varchar(200);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cbcr_entity_address_ordinal ON public.cbcr_entity_address(reporting_entity_id,address_ordinal) WHERE address_ordinal IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cbcr_const_address_ordinal ON public.cbcr_const_entity_address(const_entity_id,address_ordinal) WHERE address_ordinal IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.cbcr_const_entity_business_activity (
  const_entity_id integer NOT NULL REFERENCES public.cbcr_const_entity(const_entity_id) ON DELETE CASCADE,
  activity_ordinal integer NOT NULL,
  activity_code varchar(20) NOT NULL,
  PRIMARY KEY (const_entity_id, activity_ordinal)
);

-- Preserve the currCode attribute attached to every v2.0 monetary element.
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS revenue_unrelated_currency char(3);
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS revenue_related_currency char(3);
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS revenue_total_currency char(3);
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS profit_or_loss_currency char(3);
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS tax_paid_currency char(3);
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS tax_accrued_currency char(3);
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS capital_currency char(3);
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS earnings_currency char(3);
ALTER TABLE public.cbcr_cbcreport_summary ADD COLUMN IF NOT EXISTS assets_currency char(3);

-- AdditionalInfo children are unbounded in v2.0.
CREATE TABLE IF NOT EXISTS public.cbcr_additional_info_text (
  additional_info_id integer NOT NULL REFERENCES public.cbcr_additional_info(additional_info_id) ON DELETE CASCADE,
  info_ordinal integer NOT NULL,
  other_info text NOT NULL,
  language varchar(10),
  PRIMARY KEY (additional_info_id, info_ordinal)
);
CREATE TABLE IF NOT EXISTS public.cbcr_additional_info_country (
  additional_info_id integer NOT NULL REFERENCES public.cbcr_additional_info(additional_info_id) ON DELETE CASCADE,
  country_ordinal integer NOT NULL,
  country_code char(2) NOT NULL,
  PRIMARY KEY (additional_info_id, country_ordinal)
);
CREATE TABLE IF NOT EXISTS public.cbcr_additional_info_summary_ref (
  additional_info_id integer NOT NULL REFERENCES public.cbcr_additional_info(additional_info_id) ON DELETE CASCADE,
  summary_ref_ordinal integer NOT NULL,
  summary_ref varchar(30) NOT NULL,
  PRIMARY KEY (additional_info_id, summary_ref_ordinal)
);

-- Framework control plane.
CREATE TABLE IF NOT EXISTS cbcr_control.source (
  source_id varchar(64) PRIMARY KEY, name text NOT NULL, adapter_type varchar(40) NOT NULL,
  endpoint_link text NOT NULL, secret_ref text, enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_control.mapping_profile (
  profile_id varchar(64) NOT NULL, source_id varchar(64) NOT NULL REFERENCES cbcr_control.source(source_id),
  version integer NOT NULL, lifecycle varchar(20) NOT NULL, mapping jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), activated_at timestamptz,
  PRIMARY KEY(profile_id,version), CONSTRAINT ck_mapping_lifecycle CHECK(lifecycle IN ('draft','active','retired'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_active_mapping ON cbcr_control.mapping_profile(source_id) WHERE lifecycle='active';
CREATE TABLE IF NOT EXISTS cbcr_control.mapping_dictionary_entry (
  profile_id varchar(64) NOT NULL, mapping_version integer NOT NULL,
  logical_object varchar(30) NOT NULL, canonical_field varchar(100) NOT NULL,
  physical_schema varchar(100), physical_table varchar(200), physical_column varchar(200) NOT NULL,
  data_type varchar(100), nullable boolean NOT NULL DEFAULT true, description text,
  transform jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY(profile_id,mapping_version,logical_object,canonical_field),
  FOREIGN KEY(profile_id,mapping_version) REFERENCES cbcr_control.mapping_profile(profile_id,version)
);
CREATE TABLE IF NOT EXISTS cbcr_control.pipeline_profile (
  profile_id varchar(64) PRIMARY KEY, name text NOT NULL, route jsonb NOT NULL,
  storage_bindings jsonb NOT NULL, active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_control.lot (
  lot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_id varchar(64) NOT NULL REFERENCES cbcr_control.source(source_id),
  external_lot_ref text, status varchar(30) NOT NULL, report_count integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb, mapping_profile_id varchar(64) NOT NULL,
  mapping_version integer NOT NULL, received_by text NOT NULL, received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_control.dataset (
  dataset_id uuid NOT NULL DEFAULT gen_random_uuid(), version integer NOT NULL,
  lot_id uuid NOT NULL REFERENCES cbcr_control.lot(lot_id), zone varchar(24) NOT NULL,
  status varchar(20) NOT NULL, parent_dataset_id uuid, parent_version integer,
  pipeline_profile_id varchar(64) NOT NULL REFERENCES cbcr_control.pipeline_profile(profile_id),
  report_count integer NOT NULL DEFAULT 0, created_by text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), published_at timestamptz,
  PRIMARY KEY(dataset_id,version), CONSTRAINT ck_dataset_zone CHECK(zone IN ('landing','canonical','dq_passed','enriched','risk_ready')),
  CONSTRAINT ck_dataset_status CHECK(status IN ('draft','published','superseded'))
);
CREATE TABLE IF NOT EXISTS cbcr_control.dataset_lineage (
  lineage_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), parent_dataset_id uuid NOT NULL,
  parent_version integer NOT NULL, child_dataset_id uuid NOT NULL, child_version integer NOT NULL,
  transition varchar(100) NOT NULL, reason text, created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_control.run (
  run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL,
  dataset_version integer NOT NULL, input_zone varchar(24) NOT NULL, requested_by text NOT NULL,
  purpose varchar(40) NOT NULL, status varchar(30) NOT NULL, selected_functions jsonb NOT NULL,
  parameters jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  started_at timestamptz, completed_at timestamptz,
  FOREIGN KEY(dataset_id,dataset_version) REFERENCES cbcr_control.dataset(dataset_id,version)
);
CREATE TABLE IF NOT EXISTS cbcr_control.audit_event (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor text NOT NULL, action text NOT NULL,
  resource text NOT NULL, purpose text, decision varchar(20) NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Identical stable canonical grains in every published business-data zone.
CREATE SCHEMA IF NOT EXISTS cbcr_canonical;
CREATE SCHEMA IF NOT EXISTS cbcr_dq;
CREATE SCHEMA IF NOT EXISTS cbcr_dq_published;
CREATE SCHEMA IF NOT EXISTS cbcr_enriched;
CREATE SCHEMA IF NOT EXISTS cbcr_risk_ready;
CREATE SCHEMA IF NOT EXISTS cbcr_risk;
CREATE SCHEMA IF NOT EXISTS cbcr_selection;

CREATE TABLE IF NOT EXISTS cbcr_canonical.report (
  dataset_id uuid NOT NULL, dataset_version integer NOT NULL, report_id varchar(200) NOT NULL,
  message_ref_id varchar(170) NOT NULL, reporting_entity_id varchar(200) NOT NULL,
  reporting_entity_name varchar(500) NOT NULL, reporting_period_end date NOT NULL,
  reporting_currency char(3), receiving_jurisdiction char(2), PRIMARY KEY(dataset_id,dataset_version,report_id)
);
CREATE TABLE IF NOT EXISTS cbcr_canonical.entity (
  dataset_id uuid NOT NULL, dataset_version integer NOT NULL, report_id varchar(200) NOT NULL,
  entity_id varchar(200) NOT NULL, name varchar(500) NOT NULL, tax_jurisdiction char(2) NOT NULL,
  tin varchar(200), role varchar(100), PRIMARY KEY(dataset_id,dataset_version,report_id,entity_id)
);
CREATE TABLE IF NOT EXISTS cbcr_canonical.jurisdiction_metric (
  dataset_id uuid NOT NULL, dataset_version integer NOT NULL, report_id varchar(200) NOT NULL,
  metric_seq integer NOT NULL, jurisdiction char(2) NOT NULL, currency_code char(3),
  currency_by_measure jsonb NOT NULL DEFAULT '{}'::jsonb,
  revenue numeric(38,6), profit_before_tax numeric(38,6), income_tax_paid numeric(38,6),
  income_tax_accrued numeric(38,6), employees bigint, tangible_assets numeric(38,6),
  stated_capital numeric(38,6), accumulated_earnings numeric(38,6),
  unrelated_revenue numeric(38,6), related_revenue numeric(38,6),
  PRIMARY KEY(dataset_id,dataset_version,report_id,metric_seq)
);

CREATE TABLE IF NOT EXISTS cbcr_dq.finding (
  finding_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES cbcr_control.run(run_id),
  function_code varchar(100) NOT NULL, report_id varchar(200), entity_id varchar(200), jurisdiction char(2),
  severity varchar(20) NOT NULL, code varchar(100) NOT NULL, message text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_dq.gate_evaluation (
  evaluation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES cbcr_control.run(run_id),
  dataset_id uuid NOT NULL, dataset_version integer NOT NULL, policy jsonb NOT NULL,
  eligible_count integer NOT NULL, rejected_count integer NOT NULL, created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_dq.record_disposition (
  evaluation_id uuid NOT NULL REFERENCES cbcr_dq.gate_evaluation(evaluation_id), report_id varchar(200) NOT NULL,
  disposition varchar(20) NOT NULL, blocking_finding_count integer NOT NULL,
  reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb, PRIMARY KEY(evaluation_id,report_id)
);
CREATE TABLE IF NOT EXISTS cbcr_dq.promotion_event (
  promotion_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), source_dataset_id uuid NOT NULL,
  source_version integer NOT NULL, target_dataset_id uuid NOT NULL, target_version integer NOT NULL,
  source_zone varchar(24) NOT NULL, target_zone varchar(24) NOT NULL, evaluation_id uuid,
  promoted_count integer NOT NULL, rejected_count integer NOT NULL, requested_by text NOT NULL,
  reason text, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Create like-shaped tables without coupling function/rule columns to the schema.
CREATE TABLE IF NOT EXISTS cbcr_dq_published.report (LIKE cbcr_canonical.report INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_dq_published.entity (LIKE cbcr_canonical.entity INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_dq_published.jurisdiction_metric (LIKE cbcr_canonical.jurisdiction_metric INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_enriched.report (LIKE cbcr_canonical.report INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_enriched.entity (LIKE cbcr_canonical.entity INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_enriched.jurisdiction_metric (LIKE cbcr_canonical.jurisdiction_metric INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_risk_ready.report (LIKE cbcr_canonical.report INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_risk_ready.entity (LIKE cbcr_canonical.entity INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_risk_ready.jurisdiction_metric (LIKE cbcr_canonical.jurisdiction_metric INCLUDING ALL);
CREATE TABLE IF NOT EXISTS cbcr_enriched.attribute (
  enrichment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), dataset_id uuid NOT NULL,
  dataset_version integer NOT NULL, report_id varchar(200) NOT NULL, entity_id varchar(200),
  attribute_name varchar(200) NOT NULL, value jsonb NOT NULL, source_ref text NOT NULL,
  confidence numeric(6,5), created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_risk.result (
  risk_result_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES cbcr_control.run(run_id),
  dataset_id uuid NOT NULL, dataset_version integer NOT NULL, report_id varchar(200), entity_id varchar(200),
  jurisdiction char(2), rule_code varchar(100) NOT NULL, severity varchar(20), result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_risk.score_component (
  component_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), risk_result_id uuid NOT NULL REFERENCES cbcr_risk.result(risk_result_id),
  component_code varchar(100) NOT NULL, score numeric(18,8) NOT NULL, weight numeric(18,8), explanation text
);
CREATE TABLE IF NOT EXISTS cbcr_selection.selection_batch (
  selection_batch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), run_id uuid NOT NULL REFERENCES cbcr_control.run(run_id),
  dataset_id uuid NOT NULL, dataset_version integer NOT NULL, status varchar(20) NOT NULL,
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cbcr_selection.candidate (
  candidate_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), selection_batch_id uuid NOT NULL REFERENCES cbcr_selection.selection_batch(selection_batch_id),
  report_id varchar(200) NOT NULL, entity_id varchar(200), entity_name varchar(500), reason_code varchar(100) NOT NULL,
  score numeric(18,8), evidence jsonb NOT NULL DEFAULT '{}'::jsonb, decision varchar(20) NOT NULL DEFAULT 'pending',
  decision_rationale text, decided_by text, decided_at timestamptz
);
CREATE TABLE IF NOT EXISTS cbcr_selection.decision_history (
  decision_history_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), candidate_id uuid NOT NULL REFERENCES cbcr_selection.candidate(candidate_id),
  previous_decision varchar(20), decision varchar(20) NOT NULL, rationale text NOT NULL,
  decided_by text NOT NULL, decided_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Canonical source views over the actual XML-consumption model.
CREATE OR REPLACE VIEW cbcr_canonical.v_xml_report AS
SELECT CASE WHEN re.cbc_body_id IS NULL THEN ms.message_ref_id
            ELSE ms.message_ref_id || ':body:' || re.cbc_body_id::text END::varchar(200) AS report_id,
       ms.message_ref_id,
       re.reporting_entity_id::varchar(200) AS reporting_entity_id,
       COALESCE(onm.organisation_name, ea.name, re.name_mne_group, 'Unnamed reporting entity')::varchar(500) AS reporting_entity_name,
       COALESCE(re.reporting_period_end, ms.reporting_period) AS reporting_period_end,
       cur.currency_code AS reporting_currency,
       COALESCE(rc.country_code,
                UPPER(substring(ms.receiving_country_list from '[A-Za-z]{2}'))::char(2)) AS receiving_jurisdiction,
       ms.message_spec_id,
       re.cbc_body_id
FROM public.cbcr_message_spec ms
JOIN public.cbcr_reporting_entity re ON re.message_spec_id=ms.message_spec_id
LEFT JOIN LATERAL (SELECT organisation_name FROM public.cbcr_organisation_name n
                   WHERE n.reporting_entity_id=re.reporting_entity_id ORDER BY name_ordinal LIMIT 1) onm ON true
LEFT JOIN LATERAL (SELECT name FROM public.cbcr_entity_address a
                   WHERE a.reporting_entity_id=re.reporting_entity_id ORDER BY COALESCE(address_ordinal,entity_address_id) LIMIT 1) ea ON true
LEFT JOIN LATERAL (SELECT country_code FROM public.cbcr_message_receiving_country c
                   WHERE c.message_spec_id=ms.message_spec_id ORDER BY country_ordinal LIMIT 1) rc ON true
LEFT JOIN LATERAL (SELECT COALESCE(s.revenue_total_currency,s.currency_code) AS currency_code
                   FROM public.cbcr_cbcreport r JOIN public.cbcr_cbcreport_summary s USING(cbcreport_id)
                   WHERE r.message_spec_id=ms.message_spec_id ORDER BY r.cbcreport_id LIMIT 1) cur ON true;

CREATE OR REPLACE VIEW cbcr_canonical.v_xml_entity AS
SELECT CASE WHEN cr.cbc_body_id IS NULL THEN ms.message_ref_id
            ELSE ms.message_ref_id || ':body:' || cr.cbc_body_id::text END::varchar(200) AS report_id,
       ce.const_entity_id::varchar(200) AS entity_id,
       COALESCE(onm.organisation_name,ce.name,'Unnamed constituent entity')::varchar(500) AS name,
       COALESCE(res.country_code,ce.res_country_code)::char(2) AS tax_jurisdiction,
       ce.tin::varchar(200) AS tin,
       ce.role::varchar(100) AS role
FROM public.cbcr_const_entity ce
JOIN public.cbcr_cbcreport cr ON cr.cbcreport_id=ce.cbcreport_id
JOIN public.cbcr_message_spec ms ON ms.message_spec_id=cr.message_spec_id
LEFT JOIN LATERAL (SELECT organisation_name FROM public.cbcr_organisation_name n
                   WHERE n.const_entity_id=ce.const_entity_id ORDER BY name_ordinal LIMIT 1) onm ON true
LEFT JOIN LATERAL (SELECT country_code FROM public.cbcr_organisation_residence r
                   WHERE r.const_entity_id=ce.const_entity_id ORDER BY residence_ordinal LIMIT 1) res ON true;

CREATE OR REPLACE VIEW cbcr_canonical.v_xml_metric AS
SELECT CASE WHEN cr.cbc_body_id IS NULL THEN ms.message_ref_id
            ELSE ms.message_ref_id || ':body:' || cr.cbc_body_id::text END::varchar(200) AS report_id,
       row_number() OVER (
         PARTITION BY ms.message_ref_id,cr.cbc_body_id ORDER BY cr.cbcreport_id
       )::integer AS metric_seq,
       cr.res_country_code::char(2) AS jurisdiction,
       CASE WHEN cardinality(ARRAY_REMOVE(ARRAY[s.revenue_total_currency,s.currency_code,
            s.profit_or_loss_currency,s.tax_paid_currency,s.tax_accrued_currency,
            s.capital_currency,s.earnings_currency,s.assets_currency],NULL)) > 0
            THEN COALESCE(s.revenue_total_currency,s.currency_code) END::char(3) AS currency_code,
       jsonb_strip_nulls(jsonb_build_object(
         'revenue_unrelated',COALESCE(s.revenue_unrelated_currency,s.currency_code),
         'revenue_related',COALESCE(s.revenue_related_currency,s.currency_code),
         'revenue',COALESCE(s.revenue_total_currency,s.currency_code),
         'profit_before_tax',COALESCE(s.profit_or_loss_currency,s.currency_code),
         'income_tax_paid',COALESCE(s.tax_paid_currency,s.currency_code),
         'income_tax_accrued',COALESCE(s.tax_accrued_currency,s.currency_code),
         'stated_capital',COALESCE(s.capital_currency,s.currency_code),
         'accumulated_earnings',COALESCE(s.earnings_currency,s.currency_code),
         'tangible_assets',COALESCE(s.assets_currency,s.currency_code))) AS currency_by_measure,
       s.revenue_total AS revenue, s.profit_or_loss AS profit_before_tax,
       s.tax_paid AS income_tax_paid, s.tax_accrued AS income_tax_accrued,
       s.nb_employees::bigint AS employees, s.assets AS tangible_assets,
       s.capital AS stated_capital, s.earnings AS accumulated_earnings,
       s.revenue_unrelated AS unrelated_revenue, s.revenue_related AS related_revenue
FROM public.cbcr_cbcreport cr
JOIN public.cbcr_message_spec ms ON ms.message_spec_id=cr.message_spec_id
JOIN public.cbcr_cbcreport_summary s ON s.cbcreport_id=cr.cbcreport_id;

CREATE OR REPLACE VIEW cbcr_canonical.v_api_report_json AS
SELECT r.report_id,
       jsonb_build_object(
         'report_id',r.report_id,'message_ref_id',r.message_ref_id,
         'reporting_entity_id',r.reporting_entity_id,'reporting_entity_name',r.reporting_entity_name,
         'reporting_period_end',r.reporting_period_end,'reporting_currency',r.reporting_currency,
         'receiving_jurisdiction',r.receiving_jurisdiction,
         'entities',COALESCE((SELECT jsonb_agg(to_jsonb(e)-'report_id' ORDER BY e.entity_id)
                              FROM cbcr_canonical.v_xml_entity e WHERE e.report_id=r.report_id),'[]'::jsonb),
         'metrics',COALESCE((SELECT jsonb_agg(to_jsonb(m)-'report_id' ORDER BY m.metric_seq)
                             FROM cbcr_canonical.v_xml_metric m WHERE m.report_id=r.report_id),'[]'::jsonb)
       ) AS report_payload
FROM cbcr_canonical.v_xml_report r;

-- Seed source, mapping dictionary and ideal profile against the actual database.
INSERT INTO cbcr_control.source(source_id,name,adapter_type,endpoint_link,secret_ref)
VALUES ('local_cbcr_postgresql','Local PostgreSQL CbCR XML store','postgresql-canonical',
        'postgresql://cbcr_user@localhost:5432/cbcr?view=cbcr_canonical.v_api_report_json',
        'env:CBCR_SOURCE_DB_PASSWORD')
ON CONFLICT(source_id) DO UPDATE SET name=excluded.name,adapter_type=excluded.adapter_type,
  endpoint_link=excluded.endpoint_link,secret_ref=excluded.secret_ref,updated_at=clock_timestamp();

INSERT INTO cbcr_control.mapping_profile(profile_id,source_id,version,lifecycle,mapping,activated_at)
VALUES ('local_pg_v1','local_cbcr_postgresql',1,'active',
  '{"report":{"report_id":"report_id","message_ref_id":"message_ref_id","reporting_entity_id":"reporting_entity_id","reporting_entity_name":"reporting_entity_name","reporting_period_end":"reporting_period_end","reporting_currency":"reporting_currency","receiving_jurisdiction":"receiving_jurisdiction"},"entities":{"path":"entities","fields":{"entity_id":"entity_id","name":"name","tax_jurisdiction":"tax_jurisdiction","tin":"tin","role":"role"}},"metrics":{"path":"metrics","fields":{"jurisdiction":"jurisdiction","currency_code":"currency_code","currency_by_measure":"currency_by_measure","revenue":"revenue","profit_before_tax":"profit_before_tax","income_tax_paid":"income_tax_paid","income_tax_accrued":"income_tax_accrued","employees":"employees","tangible_assets":"tangible_assets","stated_capital":"stated_capital","accumulated_earnings":"accumulated_earnings","unrelated_revenue":"unrelated_revenue","related_revenue":"related_revenue"}}}'::jsonb,
  clock_timestamp())
ON CONFLICT(profile_id,version) DO UPDATE SET mapping=excluded.mapping,activated_at=excluded.activated_at;

INSERT INTO cbcr_control.pipeline_profile(profile_id,name,route,storage_bindings)
VALUES ('ideal_separated','Ideal separated PostgreSQL zones',
        '["landing","canonical","dq_passed","enriched","risk_ready"]'::jsonb,
        '{"landing":"cbcr_staging","canonical":"cbcr_canonical","dq_passed":"cbcr_dq_published","enriched":"cbcr_enriched","risk_ready":"cbcr_risk_ready"}'::jsonb)
ON CONFLICT(profile_id) DO UPDATE SET name=excluded.name,route=excluded.route,
  storage_bindings=excluded.storage_bindings,active=true;

INSERT INTO cbcr_control.mapping_dictionary_entry
  (profile_id,mapping_version,logical_object,canonical_field,physical_schema,physical_table,physical_column,data_type,nullable,description)
VALUES
('local_pg_v1',1,'report','report_id','cbcr_canonical','v_xml_report','report_id','varchar(200)',false,'Stable report key derived from MessageRefId'),
('local_pg_v1',1,'report','message_ref_id','public','cbcr_message_spec','message_ref_id','varchar(170)',false,'XSD MessageRefId'),
('local_pg_v1',1,'report','reporting_entity_id','public','cbcr_reporting_entity','reporting_entity_id','integer',false,'Reporting entity surrogate identifier'),
('local_pg_v1',1,'report','reporting_entity_name','cbcr_canonical','v_xml_report','reporting_entity_name','varchar(500)',false,'First organisation name with compatible fallbacks'),
('local_pg_v1',1,'report','reporting_period_end','public','cbcr_reporting_entity','reporting_period_end','date',false,'ReportingPeriod EndDate'),
('local_pg_v1',1,'report','reporting_currency','cbcr_canonical','v_xml_report','reporting_currency','char(3)',true,'Representative currency; per-measure currencies retained on metrics'),
('local_pg_v1',1,'report','receiving_jurisdiction','public','cbcr_message_receiving_country','country_code','char(2)',true,'First receiving jurisdiction for processing context'),
('local_pg_v1',1,'entity','entity_id','public','cbcr_const_entity','const_entity_id','integer',false,'Constituent entity surrogate identifier'),
('local_pg_v1',1,'entity','name','cbcr_canonical','v_xml_entity','name','varchar(500)',false,'First organisation name with legacy fallback'),
('local_pg_v1',1,'entity','tax_jurisdiction','cbcr_canonical','v_xml_entity','tax_jurisdiction','char(2)',false,'First residence jurisdiction'),
('local_pg_v1',1,'entity','tin','public','cbcr_const_entity','tin','varchar(200)',true,'Tax identification number'),
('local_pg_v1',1,'entity','role','public','cbcr_const_entity','role','varchar(100)',true,'Ultimate-parent role where applicable'),
('local_pg_v1',1,'metric','jurisdiction','public','cbcr_cbcreport','res_country_code','char(2)',false,'Jurisdiction for Summary and ConstEntities'),
('local_pg_v1',1,'metric','currency_code','cbcr_canonical','v_xml_metric','currency_code','char(3)',true,'Representative currency'),
('local_pg_v1',1,'metric','currency_by_measure','cbcr_canonical','v_xml_metric','currency_by_measure','jsonb',false,'Lossless currCode mapping per monetary measure'),
('local_pg_v1',1,'metric','revenue','public','cbcr_cbcreport_summary','revenue_total','numeric',true,'Total revenue'),
('local_pg_v1',1,'metric','profit_before_tax','public','cbcr_cbcreport_summary','profit_or_loss','numeric',true,'Profit or loss before tax'),
('local_pg_v1',1,'metric','income_tax_paid','public','cbcr_cbcreport_summary','tax_paid','numeric',true,'Income tax paid'),
('local_pg_v1',1,'metric','income_tax_accrued','public','cbcr_cbcreport_summary','tax_accrued','numeric',true,'Income tax accrued'),
('local_pg_v1',1,'metric','employees','public','cbcr_cbcreport_summary','nb_employees','integer',true,'Number of employees'),
('local_pg_v1',1,'metric','tangible_assets','public','cbcr_cbcreport_summary','assets','numeric',true,'Tangible assets'),
('local_pg_v1',1,'metric','stated_capital','public','cbcr_cbcreport_summary','capital','numeric',true,'Stated capital'),
('local_pg_v1',1,'metric','accumulated_earnings','public','cbcr_cbcreport_summary','earnings','numeric',true,'Accumulated earnings'),
('local_pg_v1',1,'metric','unrelated_revenue','public','cbcr_cbcreport_summary','revenue_unrelated','numeric',true,'Unrelated party revenue'),
('local_pg_v1',1,'metric','related_revenue','public','cbcr_cbcreport_summary','revenue_related','numeric',true,'Related party revenue')
ON CONFLICT(profile_id,mapping_version,logical_object,canonical_field) DO UPDATE SET
 physical_schema=excluded.physical_schema,physical_table=excluded.physical_table,
 physical_column=excluded.physical_column,data_type=excluded.data_type,nullable=excluded.nullable,
 description=excluded.description;

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES ('001_cbcr_framework','Complete CbCR XML v2.0 cardinalities and add framework data zones')
ON CONFLICT(migration_id) DO NOTHING;

COMMIT;
