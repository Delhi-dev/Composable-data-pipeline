BEGIN;

CREATE OR REPLACE FUNCTION cbcr_control.protect_xml_payload()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.raw_payload IS DISTINCT FROM NEW.raw_payload
     OR xmlserialize(CONTENT OLD.xml_payload AS text) IS DISTINCT FROM xmlserialize(CONTENT NEW.xml_payload AS text)
     OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256
  THEN
    RAISE EXCEPTION 'XML payload and digest are immutable after staging';
  END IF;
  RETURN NEW;
END;
$$;

COMMIT;
