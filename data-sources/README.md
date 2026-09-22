# Data Sources

Each independent data source is an autonomous system (DB / XML repository) that talks to
the pipeline **only through its published API**. For every source you get:

- `openapi.yaml` — the published API contract (endpoints, parameters, schemas).
- `data_dictionary.md` — the functional data dictionary (fields, types, keys, sensitivity).

Engines never read a source's database directly; they call the API declared in
`config/data_source_endpoints.yaml`, which points at these specs. This keeps each source
swappable and keeps the **CbCR store isolated** (flags-only egress).

| Source | Form / basis | Transport | Role |
|--------|--------------|-----------|------|
| `cbcr-store` | OECD CbCR XML | api (enclave) | inbound CbCR — flags-only egress |
| `domestic-taxpayer-registry` | Registry master | api | entity resolution |
| `transfer-pricing-return` | 3CEB / TPDF | db_link | related-party transactions |
| `outward-remittance` | 15CA-15CB / WHT | api | remittances + applied WHT |
| `corporate-return` | ITR / CIT-001 | db_link | turnover, EBITDA, deductions |
| `audited-financials` | IFRS accounts | api | debt/equity, stated capital |
| `case-management` | Case pack | api (sink) | receives approved cases |
