\set ON_ERROR_STOP on
BEGIN;

-- Preserve original bytes even where the XML is malformed and cannot be cast to PostgreSQL xml.
ALTER TABLE cbcr_staging.xml_document ALTER COLUMN xml_payload DROP NOT NULL;
ALTER TABLE cbcr_staging.xml_document ADD COLUMN IF NOT EXISTS raw_payload bytea;
ALTER TABLE cbcr_staging.xml_document ADD COLUMN IF NOT EXISTS content_size_bytes bigint;
ALTER TABLE cbcr_staging.xml_document
  ADD CONSTRAINT ck_xml_document_payload_present CHECK (raw_payload IS NOT NULL OR xml_payload IS NOT NULL) NOT VALID;
CREATE INDEX IF NOT EXISTS idx_xml_document_status_received ON cbcr_staging.xml_document(parse_status, received_at);

CREATE TABLE IF NOT EXISTS cbcr_staging.xml_ingestion_attempt (
  ingestion_attempt_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  xml_document_id bigint NOT NULL REFERENCES cbcr_staging.xml_document(xml_document_id) ON DELETE CASCADE,
  attempt_ordinal integer NOT NULL,
  parser_version varchar(100) NOT NULL,
  outcome varchar(30) NOT NULL,
  started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  completed_at timestamptz,
  message text,
  CONSTRAINT uq_xml_ingestion_attempt UNIQUE(xml_document_id, attempt_ordinal),
  CONSTRAINT ck_xml_ingestion_attempt_outcome CHECK (outcome IN ('started','schema_valid','schema_invalid','parsed','parse_failed','duplicate'))
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cbcr_xml_ingestor') THEN
    CREATE ROLE cbcr_xml_ingestor NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public, cbcr_staging TO cbcr_xml_ingestor;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA cbcr_staging TO cbcr_xml_ingestor;
GRANT SELECT, INSERT, UPDATE ON TABLE public.cbcr_message_spec, public.cbcr_body,
  public.cbcr_message_receiving_country, public.cbcr_message_correction_ref,
  public.cbcr_reporting_entity, public.cbcr_entity_address,
  public.cbcr_cbcreport, public.cbcr_cbcreport_summary, public.cbcr_const_entity,
  public.cbcr_const_entity_address, public.cbcr_const_entity_business_activity,
  public.cbcr_additional_info, public.cbcr_additional_info_text,
  public.cbcr_additional_info_country, public.cbcr_additional_info_summary_ref,
  public.cbcr_document_correction_ref, public.cbcr_organisation_residence,
  public.cbcr_organisation_identifier, public.cbcr_organisation_name TO cbcr_xml_ingestor;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public, cbcr_staging TO cbcr_xml_ingestor;
GRANT cbcr_xml_ingestor TO cbcr_user;

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES ('009_xml_ingestion_runtime','Add raw XML preservation, ingestion attempts and parser-role grants')
ON CONFLICT(migration_id) DO NOTHING;
COMMIT;
