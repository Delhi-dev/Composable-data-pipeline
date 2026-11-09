# Simplified UI implementation status and open issues

**Implemented:** 6 November 2026  
**Source proposal:** `UI_REDESIGN_PROPOSAL.md` and the static mockups in `mockups/`  
**Runtime:** PostgreSQL control plane (`cbcr_platform_pg.api`)

## Reviewer remediation update (8 November 2026)

The browser-review findings in `UI_REVIEW_FINDINGS.md` have now been applied to the standard UI and supporting APIs.

### Resolved

- **Shell and accessibility (A-1 to A-8):** the ambiguous OK control is now a System status menu; profile and system menus close on outside click and Escape; persona and roles are consolidated; global identifier lookup is present; dialog Cancel/Close bypasses validation; identifier chips expand separately from copy; responsive navigation and identifier casing are corrected.
- **Roles and scope (B-1, B-2, B-4, B-5, C-7):** dashboard cards represent actual pending work; administrators can read the audit log; case reviewers receive case-workbench scope; Settings exposes users, sources, profiles, functions/mappings and system status; development impersonation is available only when `CBCR_UI_IMPERSONATION=1`.
- **Lifecycle and workspace (D-1, D-4 to D-10, D-12 to D-17):** snapshots are grouped into per-lot stage timelines; lot lookup is honoured; the workspace shows lot context and correct report fields; parameters are typed and collapsible; runs inspect inline; data is cached per dataset version; DQ uses evaluate/preview/publish; lineage uses the real API response shape; enrichment supports multiple rows; dependent risk IDs are selected from eligible prior runs and artifacts.
- **Cases, reports and oversight (D-18 to D-25):** the workbench shows progress, saved rationales and decision metadata; finalized batches are read-only; finalization has a readiness checklist; report library filters and readable scores are present; audit-case lineage is a structured timeline; lookup guidance is clearer.
- **Catalogue and seed data (E-1, E-5, E-6):** acceptance users are hidden by default with an explicit toggle, retired functions are hidden by default, and roles have plain-language descriptions.

### Partially resolved or deliberately deferred

- **B-3 — trusted production identity:** development impersonation is now feature-gated. A real reverse-proxy/IdP integration and removal of the default development identity remain production deployment work.
- **D-2 — large-result pagination:** the lifecycle page is bounded and paged in the client after a capped server query. APIs still need total-count or cursor metadata for genuinely large installations.
- **D-3 — intake preview:** All/By-ID selection, duplicate removal and a unique-ID count are present. Source-side dry-run counts and a searchable server-backed report picker are not yet implemented.
- **E-1 — test-data isolation:** test entries are hidden in normal administration views. Existing acceptance records were not deleted because that is destructive; acceptance tests should ultimately use a dedicated database and cleanup policy.

### Verification performed

- JavaScript module syntax checks: passed.
- Python compilation: passed.
- Static UI/backend contract suite: **28 passed**.
- Targeted PostgreSQL redesign suite: **5 passed**.
- Full PostgreSQL suite: **16 passed, 1 environment-conflicted**. The remaining exactly-once worker assertion ran while an older local application instance on port 8011 was consuming three queued test jobs; Windows denied stopping that separately-owned process. This is not an application assertion failure when workers are isolated.
- Updated runtime on port 8012: health OK, PostgreSQL backend active, redesigned entry point served. The built-in browser automation helper could not initialize because its local kernel-assets directory was unavailable, so no screenshot-regression result is claimed.

## 1. Outcome

The proposal is implemented as a new standard workflow UI at `/`. The former detailed interface has not been removed or overwritten; it is available at `/advanced`. Swagger remains at `/docs`.

The standard UI reduces the top-level workflow to:

1. Home
2. Data lifecycle
3. Run history
4. Case workbench
5. Reports
6. Oversight, when the current user has auditor or platform-administrator access

Function reference and Settings are utilities rather than primary workflow pages. Settings is shown only to platform administrators.

## 2. Implemented pages and behaviour

### Home

- Replaces the unbounded work queue with attention cards, 30-day stage/run summaries and a bounded recent-run table.
- Labels recent activity accurately as function runs.
- Moves backend/database information under **System and database details**.

### Data lifecycle

- Search by dataset, lot ID or external lot reference.
- Filter by stage and date; auditors/administrators can also filter owner and scope.
- Ordinary users default to lots they initiated.
- The intake dialog fixes the standard journey to `ideal_separated`, hides that technical choice, and explains the optional report subset. Alternate profiles remain in the advanced interface.
- Opens a routed dataset workspace rather than expanding the whole lifecycle page.

### Dataset workspace

- Stable URL: `/datasets/{dataset_id}/v{version}/{tab}`.
- Stage rail, immutable snapshot context and tabs for overview, data, functions, results, publishing and lineage.
- Function cards come from the database catalogue; parameter inputs come from `parameter_schema`.
- Function availability is limited by the current stage and purpose.
- DQ publication performs gate evaluation before promotion.
- Enrichment fields are optional and explained in the publication form.
- The next publication zone comes from the dataset's pipeline profile; it is not chosen by the user.

### Run history

- Server-side filters for status, purpose, function, zone, owner, dates and search text.
- Full IDs expand and copy when clicked.
- **Inspect** expands immediately beneath its own row.
- Child function status, resolved parameters, summaries, artifacts, errors and findings are presented together.
- An empty findings list is explained as “no configured exception found,” not as an empty execution.

### Case workbench

- Starts from a filtered risk-ready dataset.
- Shows completed risk runs for that exact dataset version.
- Creates a named draft risk evidence set and requires explicit approval.
- Automatically injects the approved `risk_result_set_id` into `generate_case_candidates`.
- Shows existing batches without replacing or mutating them.
- Provides candidate search, score and decision filters.
- Requires a rationale for selected, not-selected and deferred decisions.
- Finalizes selected candidates into an immutable case set and audit-handoff rows.

The proposal's separate “risk runs” and “evidence set” screens are combined into one evidence step. The functional controls remain distinct, but this reduces the guide from six visual steps to five.

### Reports

- A report library lists finalized case sets.
- **Final selected cases** presents human decisions, rationale, risk evidence and audit-handoff state.
- **Lineage and execution trace** presents dataset ancestry, promotions, run IDs, functions and resolved parameters.
- Both reports support CSV download and server-generated PDF download. The selected-case PDF contains a formal register plus detailed case attributes, human rationale, audit-handoff details, source-document references and risk evidence; the lineage PDF contains dataset, promotion, function-run and selected-case provenance. Neither is an HTML-page printout.

### Oversight

- Direct identifier lookup supports lot/external reference, dataset, run, risk evidence set, selection batch, final case set and audit case.
- Audit-case lookup renders its end-to-end lineage.
- Access/action audit filters actor, current role, action, outcome, target and date range.
- The page explains that allowed/denied is an access-control decision, not a case-selection decision.

### Settings and function reference

- Administrators can create/reactivate users, assign many roles, deactivate users and edit source definitions.
- The current user cannot deactivate itself.
- Function reference groups catalogue entries by stage and explains configured parameters and outputs.

## 3. Backend changes

No database migration was required. Existing schema objects already store:

- lot ownership (`cbcr_control.lot.received_by`);
- dataset provenance and creator;
- run requester and timestamps;
- user status and many-to-many roles;
- immutable risk-result sets, candidate evidence, decisions, case sets and audit cases;
- access/action audit events.

The implementation adds API/service behaviour over those objects:

- `GET /api/v1/me`;
- `GET /api/v1/dashboard`;
- `GET /api/v1/lookup`;
- filters/pagination for lots, datasets, runs, candidates and audit events;
- scope-aware lists for risk-result sets, selection batches and case sets;
- `PUT /api/v1/users/{user_id}/status`;
- risk-result-set list summaries now include their source run provenance;
- browser-history routes for every standard UI deep link.

Ordinary-user list scope uses the initiating lot's `received_by`. Auditor/platform-admin scope may include all users. This is implemented in API queries and is not merely a frontend filter.

## 4. Main code locations

Backend:

- `platform/cbcr_platform_pg/api.py`
- `platform/cbcr_platform_pg/admin.py`
- `platform/cbcr_platform_pg/data_plane.py`
- `platform/cbcr_platform_pg/runs.py`
- `platform/cbcr_platform_pg/risk_result_sets.py`
- `platform/cbcr_platform_pg/case_handoff.py`
- `platform/cbcr_platform/contracts.py`

Standard UI:

- `platform/cbcr_platform/web/standard.html`
- `platform/cbcr_platform/web/redesign.css`
- `platform/cbcr_platform/web/app/`

Retained advanced UI:

- `platform/cbcr_platform/web/index.html`
- `platform/cbcr_platform/web/niche.js`
- served at `/advanced`

Verification:

- `platform/tests/test_ui_redesign_static.py`
- `platform/tests_postgresql/test_pg_ui_redesign.py`

## 5. Deliberately unresolved production issues

### P0 — real authentication and trusted identity

The application still derives the current user from the development `X-CBCR-User` header, defaulting to `demo`. The standard UI removes the visible impersonation dropdown, but that is not authentication. Before production, a trusted reverse proxy or identity provider must authenticate the user, map its immutable subject to `user_account.external_subject`, and strip any client-supplied identity header.

### P0 — object-level authorization policy

List endpoints now enforce initiating-user scope for ordinary users. Some existing single-object endpoints still rely on role/action permission rather than verifying ownership or a case assignment. A production policy must decide whether analysts may collaborate on a lot, whether ownership transfers, and how case assignment works. Once decided, the same policy should be applied to every direct dataset, run, case-set and lookup endpoint; PostgreSQL row-level security may be added as defence in depth.

### P1 — historical role evidence in audit

The role filter and role display use the actor's current roles. Audit events do not yet snapshot roles, permission decision inputs, request/correlation ID, client address or authentication subject at event time. A future migration should add those immutable fields if evidential audit requirements demand them.

### P1 — pagination totals and saved views

Server-side limits and page offsets exist, but responses do not expose total row counts or continuation metadata. The current UI therefore shows bounded results rather than a full paginator. Saved filters/views are also not implemented.

### P1 — intake preview and source testing

The standard intake dialog explains report subsets but cannot query a source for a dry-run count or build a subset from reporting period/jurisdiction criteria. Settings can update a source but has no “test connection” endpoint, health history or last-success timestamp.

### P2 — run control

Retry/cancel actions are not exposed because durable cancellation and retry semantics are not yet defined for partially completed multi-function runs.

### P2 — administration depth

Pipeline-profile versioning, mapping-dictionary editing and function-definition lifecycle management remain in `/advanced` and Swagger. This is intentional until guarded, task-focused admin flows are designed.

### P2 — browser visual regression suite

Static contracts, JavaScript syntax, API routes and PostgreSQL integration are tested. A browser visual-regression suite with screenshots and keyboard/accessibility checks should be added to CI. The computer-use browser was unavailable in the implementation environment, so visual verification was limited to the supplied mockup contracts and rendered HTML/CSS structure.

## 6. Acceptance criteria for a deployment

1. `/` loads the standard UI and `/advanced` loads the retained detailed UI.
2. An analyst sees only their initiated lots in lifecycle lists.
3. An auditor can switch to all-user scope and see Oversight.
4. A platform administrator sees Settings and can assign multiple roles.
5. A canonical dataset can run DQ functions, evaluate a gate and publish DQ-passed.
6. DQ-passed can publish enriched, and enriched can publish risk-ready.
7. A risk-ready dataset can create and approve an evidence set, generate candidates, record decisions and finalize a case set.
8. Both final reports render and download CSV.
9. Full IDs are obtainable without searching another page.
10. A denied access event is clearly distinguished from a case-selection decision.
