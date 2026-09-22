\set ON_ERROR_STOP on
BEGIN;

-- Password is intentionally not stored here. Set it separately through an approved secret.
ALTER ROLE cbcr_user LOGIN;
GRANT CONNECT ON DATABASE cbcr TO cbcr_user;
GRANT USAGE ON SCHEMA public,cbcr_staging,cbcr_control,cbcr_canonical,cbcr_dq,
  cbcr_dq_published,cbcr_enriched,cbcr_risk_ready,cbcr_risk,cbcr_selection TO cbcr_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cbcr_user;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA cbcr_staging,cbcr_control,cbcr_canonical,
  cbcr_dq,cbcr_dq_published,cbcr_enriched,cbcr_risk_ready,cbcr_risk,cbcr_selection TO cbcr_user;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public,cbcr_staging,cbcr_control,cbcr_canonical,
  cbcr_dq,cbcr_dq_published,cbcr_enriched,cbcr_risk_ready,cbcr_risk,cbcr_selection TO cbcr_user;

ALTER DEFAULT PRIVILEGES IN SCHEMA cbcr_staging,cbcr_control,cbcr_canonical,cbcr_dq,
  cbcr_dq_published,cbcr_enriched,cbcr_risk_ready,cbcr_risk,cbcr_selection
  GRANT SELECT,INSERT,UPDATE ON TABLES TO cbcr_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA cbcr_staging,cbcr_control,cbcr_canonical,cbcr_dq,
  cbcr_dq_published,cbcr_enriched,cbcr_risk_ready,cbcr_risk,cbcr_selection
  GRANT USAGE,SELECT ON SEQUENCES TO cbcr_user;

COMMIT;
