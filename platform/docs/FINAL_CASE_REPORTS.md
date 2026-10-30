# Final Case Reports

## Purpose

The application generates two read-only reports for a finalized case set:

1. **Final selected cases** — the cases approved by human review and frozen into the selected case set.
2. **Final case-set lineage and execution trace** — the path from the intake datasets to the final case set, including dataset IDs, run IDs, function runs, effective function parameters, promotion events, approved risk evidence and human decisions.

The reports are generated from existing governed records. They do not copy or alter operational data, and they require no additional database migration.

## Frontend navigation

1. Complete candidate decisions and select **Finalize Audit Case Set** in **Case workbench**.
2. Open **Final reports** from the left navigation.
3. Choose the required final case set.
4. Select **Generate reports**.
5. View the two reports on screen, use **Download Cases CSV** or **Download Lineage CSV**, or select **Print**.

The **Final case sets** list in **Case workbench** also has a **Reports** link that opens the same report workspace with that case set selected.

Both a case-management user with stage-07 result access and an auditor with audit-view access may view these reports. Existing access-control rules are reused.

## Report 1: final selected cases

The report contains:

- case-set ID, name, version, status and finalization details;
- final dataset ID and version;
- audit-case ID and current handoff status;
- report and entity identifiers/names;
- reason code and score;
- the human selection decision, rationale, user and timestamp;
- source risk functions, risk-result IDs and run IDs;
- external audit reference, when assigned; and
- originating XML/document information when it was captured during finalization.

API endpoints:

- `GET /api/v1/case-sets/{case_set_id}/reports/selected-cases`
- `GET /api/v1/case-sets/{case_set_id}/reports/selected-cases.csv`

## Report 2: lineage and execution trace

The report contains:

- ordered dataset ancestry from landing to risk-ready, with IDs, versions, zones, parents and transition reasons;
- all runs recorded against every dataset in that ancestry;
- every child function run, including function code/version, stage, status, effective parameters and result summary/error;
- publication/promotion events, DQ gate run IDs and gate policies where applicable;
- the approved Risk Result Set, selection policy, approver and included risk run IDs;
- selected cases and their human decision rationale; and
- the links from selected cases back to source risk results and source document snapshots.

API endpoints:

- `GET /api/v1/case-sets/{case_set_id}/reports/lineage`
- `GET /api/v1/case-sets/{case_set_id}/reports/lineage.csv`

The lineage CSV uses a `record_type` column. `DATASET_FUNCTION` rows describe execution; `DATASET` rows preserve stages without runs; and `SELECTED_CASE` rows record the final case handoff.

## Implementation locations

- Report queries and CSV generation: `platform/cbcr_platform_pg/reports.py`
- API endpoints: `platform/cbcr_platform_pg/api.py`
- Service registration: `platform/cbcr_platform_pg/container.py`
- Frontend report workspace: `platform/cbcr_platform/web/index.html` and `niche.js`
- Report styling and print layout: `platform/cbcr_platform/web/reports.css`
- PostgreSQL acceptance coverage: `platform/tests_postgresql/test_pg_acceptance.py`
