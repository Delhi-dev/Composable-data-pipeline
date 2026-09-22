\set ON_ERROR_STOP on
BEGIN;

-- A stand-alone schema that represents the remote domestic PostgreSQL source.
-- Production deployments replace the local adapter with a separately credentialled
-- PostgreSQL repository; scenario code never names these physical objects.
CREATE SCHEMA IF NOT EXISTS cbcr_domestic_demo;
CREATE TABLE IF NOT EXISTS cbcr_domestic_demo.taxpayer (
  domestic_tin text PRIMARY KEY, legal_name text NOT NULL, taxpayer_status text NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS cbcr_domestic_demo.entity_financial_summary (
  domestic_tin text NOT NULL REFERENCES cbcr_domestic_demo.taxpayer(domestic_tin), fiscal_year integer NOT NULL,
  revenue numeric NOT NULL, profit_before_tax numeric NOT NULL, interest_expense_total numeric NOT NULL,
  depreciation_amortisation numeric NOT NULL, related_borrowings numeric NOT NULL, equity numeric NOT NULL,
  PRIMARY KEY(domestic_tin,fiscal_year)
);
CREATE TABLE IF NOT EXISTS cbcr_domestic_demo.entity_interest_summary (
  domestic_tin text NOT NULL REFERENCES cbcr_domestic_demo.taxpayer(domestic_tin), fiscal_year integer NOT NULL,
  interest_expense_related numeric NOT NULL, interest_disallowed_in_return numeric NOT NULL DEFAULT 0,
  average_related_borrowings numeric, closing_related_borrowings numeric NOT NULL,
  weighted_average_rate_third_party numeric, PRIMARY KEY(domestic_tin,fiscal_year)
);
CREATE TABLE IF NOT EXISTS cbcr_domestic_demo.outbound_payment (
  payment_id bigserial PRIMARY KEY, domestic_tin text NOT NULL REFERENCES cbcr_domestic_demo.taxpayer(domestic_tin),
  fiscal_year integer NOT NULL, payee_jurisdiction text NOT NULL, payment_nature text NOT NULL,
  gross_amount numeric NOT NULL, tax_withheld numeric NOT NULL DEFAULT 0, payee_identifier text NOT NULL,
  is_associated_enterprise boolean NOT NULL, payment_date date NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_domestic_payment_reduce ON cbcr_domestic_demo.outbound_payment(domestic_tin,fiscal_year,payment_nature);

-- Auditable, confidence-scored CbC-to-domestic mapping.  This is intentionally
-- separate from either source and avoids treating placeholder CbC TINs as matches.
CREATE TABLE IF NOT EXISTS cbcr_risk.domestic_entity_link (
  report_id text NOT NULL, cbc_entity_id text NOT NULL, domestic_tin text NOT NULL REFERENCES cbcr_domestic_demo.taxpayer(domestic_tin),
  match_method text NOT NULL, confidence numeric NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  PRIMARY KEY(report_id,cbc_entity_id)
);
CREATE TABLE IF NOT EXISTS cbcr_risk.domestic_risk_context (
  context_id uuid PRIMARY KEY, dataset_id uuid NOT NULL, dataset_version integer NOT NULL,
  screening_run_id uuid NOT NULL, fiscal_year integer NOT NULL, report_ids jsonb NOT NULL,
  payload jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(dataset_id,dataset_version,screening_run_id,fiscal_year)
);

INSERT INTO cbcr_domestic_demo.taxpayer(domestic_tin,legal_name) VALUES
 ('DOM-S1-100','Synthetic One Domestic Ltd'), ('DOM-S2-100','Synthetic Two Domestic Ltd') ON CONFLICT DO NOTHING;
INSERT INTO cbcr_domestic_demo.entity_financial_summary VALUES
 ('DOM-S1-100',2025,100000000,9000000,8500000,2000000,80000000,15000000),
 ('DOM-S2-100',2025,80000000,6000000,1000000,1500000,5000000,40000000) ON CONFLICT DO NOTHING;
INSERT INTO cbcr_domestic_demo.entity_interest_summary VALUES
 ('DOM-S1-100',2025,7000000,0,70000000,80000000,0.045),
 ('DOM-S2-100',2025,500000,0,5000000,5000000,0.055) ON CONFLICT DO NOTHING;
INSERT INTO cbcr_domestic_demo.outbound_payment(domestic_tin,fiscal_year,payee_jurisdiction,payment_nature,gross_amount,tax_withheld,payee_identifier,is_associated_enterprise,payment_date) VALUES
 ('DOM-S1-100',2025,'YU','ROYALTY',18000000,90000,'YU-IP-01',true,'2025-03-31'),
 ('DOM-S1-100',2025,'YU','INTEREST',6500000,65000,'YU-FIN-01',true,'2025-09-30'),
 ('DOM-S2-100',2025,'WU','SERVICE_FEE',250000,25000,'WU-SVC-01',true,'2025-06-30') ON CONFLICT DO NOTHING;
INSERT INTO cbcr_risk.domestic_entity_link(report_id,cbc_entity_id,domestic_tin,match_method,confidence) VALUES
 ('Synthetic_1','100','DOM-S1-100','manual_demo',0.99),
 ('Synthetic_2','100','DOM-S2-100','manual_demo',0.99) ON CONFLICT DO NOTHING;
GRANT USAGE ON SCHEMA cbcr_domestic_demo TO cbcr_user;
GRANT SELECT ON ALL TABLES IN SCHEMA cbcr_domestic_demo TO cbcr_user;
GRANT SELECT ON cbcr_risk.domestic_entity_link TO cbcr_user;
GRANT SELECT,INSERT ON cbcr_risk.domestic_risk_context TO cbcr_user;

INSERT INTO cbcr_control.schema_migration(migration_id,description)
VALUES ('008_domestic_risk_demo','Domestic PostgreSQL demo source, explicit entity links and aggregated-risk indexes')
ON CONFLICT(migration_id) DO NOTHING;
COMMIT;
