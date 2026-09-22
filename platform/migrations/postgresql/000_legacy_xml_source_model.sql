\set ON_ERROR_STOP on
BEGIN;

-- Baseline XML-shaped source model. Later migrations only extend this model additively.
CREATE TABLE IF NOT EXISTS public.cbcr_message_spec (
  message_spec_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sending_entity_in varchar(200), transmitting_country char(2), receiving_country_list text,
  message_type varchar(20), language varchar(10), message_ref_id varchar(170) NOT NULL UNIQUE,
  message_type_indic varchar(20), reporting_period date, timestamp timestamp,
  created_at timestamp DEFAULT now(), updated_at timestamp DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.cbcr_reporting_entity (
  reporting_entity_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_spec_id integer NOT NULL REFERENCES public.cbcr_message_spec(message_spec_id) ON DELETE CASCADE,
  name_mne_group varchar(200), reporting_role varchar(20), reporting_period_start date,
  reporting_period_end date, doc_type_indic varchar(20), doc_ref_id varchar(200) UNIQUE,
  created_at timestamp DEFAULT now(), updated_at timestamp DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.cbcr_entity_address (
  entity_address_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  reporting_entity_id integer NOT NULL REFERENCES public.cbcr_reporting_entity(reporting_entity_id) ON DELETE CASCADE,
  res_country_code char(2), tin varchar(200), tin_issued_by char(2), in_number varchar(200),
  name varchar(200), country_code char(2), address_free text,
  created_at timestamp DEFAULT now(), updated_at timestamp DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.cbcr_cbcreport (
  cbcreport_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_spec_id integer NOT NULL REFERENCES public.cbcr_message_spec(message_spec_id) ON DELETE CASCADE,
  res_country_code char(2), doc_type_indic varchar(20), doc_ref_id varchar(200) UNIQUE,
  created_at timestamp DEFAULT now(), updated_at timestamp DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.cbcr_cbcreport_summary (
  summary_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cbcreport_id integer NOT NULL REFERENCES public.cbcr_cbcreport(cbcreport_id) ON DELETE CASCADE,
  revenue_unrelated numeric, revenue_related numeric, revenue_total numeric, currency_code char(3),
  profit_or_loss numeric, tax_paid numeric, tax_accrued numeric, capital numeric, earnings numeric,
  nb_employees integer, assets numeric, created_at timestamp DEFAULT now(), updated_at timestamp DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.cbcr_const_entity (
  const_entity_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cbcreport_id integer NOT NULL REFERENCES public.cbcr_cbcreport(cbcreport_id) ON DELETE CASCADE,
  res_country_code char(2), tin varchar(200), tin_issued_by char(2), in_number varchar(200),
  name varchar(200), incorp_country_code char(2), role varchar(100), biz_activities text,
  other_entity_info text, created_at timestamp DEFAULT now(), updated_at timestamp DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.cbcr_const_entity_address (
  const_entity_address_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  const_entity_id integer NOT NULL REFERENCES public.cbcr_const_entity(const_entity_id) ON DELETE CASCADE,
  country_code char(2), address_free text, created_at timestamp DEFAULT now(), updated_at timestamp DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.cbcr_additional_info (
  additional_info_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  message_spec_id integer NOT NULL REFERENCES public.cbcr_message_spec(message_spec_id) ON DELETE CASCADE,
  doc_type_indic varchar(20), doc_ref_id varchar(200) UNIQUE, other_info text, language varchar(10),
  res_country_code char(2), summary_ref varchar(30), created_at timestamp DEFAULT now(), updated_at timestamp DEFAULT now()
);
COMMIT;
