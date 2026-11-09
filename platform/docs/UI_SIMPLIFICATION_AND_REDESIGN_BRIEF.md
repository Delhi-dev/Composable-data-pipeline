# CbCR Pipeline UI Simplification and Redesign Brief

**Status:** Design-review draft for discussion with another LLM/design reviewer  
**Prepared:** 6 November 2026  
**Scope:** The current CbCR web interface only. This document does not implement the redesign.

## 1. Purpose of this document

The current interface exposes nearly every platform capability as a first-level page. That is useful during development and troubleshooting, but it makes the normal analyst journey appear more complicated than it is.

This document:

- explains the purpose and workflow of the CbCR platform;
- describes what every current page and important field does;
- records the observed usability issues;
- proposes page-by-page changes for a simpler standard workflow;
- proposes retaining the present interface, with minor improvements, as an advanced operations/control-plane view;
- identifies role and API dependencies that a frontend redesign cannot solve by itself; and
- gives local code paths so another LLM or designer can inspect the implementation and comment at code level.

The requested output from a design reviewer is an opinion on the information architecture, workflow presentation, page composition, terminology, progressive disclosure, role-based visibility, and component-level implementation approach.

## 2. Solution background

The application processes Country-by-Country Reporting (CbCR) data held in PostgreSQL. XML ingestion is handled before the main analytical workflow: the XML is preserved and parsed into database structures. The control-plane UI then creates governed datasets and moves them through immutable processing stages.

The platform is deliberately composable:

- a **lot** represents one intake operation;
- a **dataset** is an immutable snapshot of the lot at a particular processing zone;
- a **run** executes one or more independent functions against one dataset version;
- a **function** is a configurable data-quality, enrichment, risk-analysis, or case-generation rule;
- a **finding** is a rule outcome requiring attention; a successful run can validly have no findings;
- a **promotion** creates the next immutable dataset rather than overwriting the current one;
- a **risk-result set** freezes the exact completed risk runs approved as evidence for case generation;
- a **selection batch** contains candidates generated from an approved risk-result set;
- a **case set** freezes the candidates finally selected by human reviewers; and
- an **audit handoff case** is an individual selected case ready for work outside this software.

The primary governed flow is:

```text
XML source data
  -> Intake lot
  -> Landing snapshot
  -> Canonical snapshot
  -> Data-quality functions
  -> DQ gate
  -> DQ-passed snapshot
  -> Optional governed enrichment
  -> Enriched snapshot
  -> Risk-ready snapshot
  -> Risk-analysis functions
  -> Approved risk-result set
  -> Candidate-generation run
  -> Selection batch
  -> Human decisions
  -> Final case set / audit handoff cases
  -> Final reports and lineage/audit review
```

Runs are asynchronous. Functions selected in the same parent run execute independently; one function's output is not automatically the input to another function in that run.

## 3. Current implementation and local code locations

Repository root:

```text
C:\Users\177885\Desktop\UP_West\TIWB\Work\CbCR_India_Approach\Railway\Composable-data-pipeline-railway
```

Principal UI files:

```text
platform\cbcr_platform\web\index.html
platform\cbcr_platform\web\niche.js
platform\cbcr_platform\web\niche.css
platform\cbcr_platform\web\wip-workbench.css
platform\cbcr_platform\web\reports.css
```

Relevant API and UI-supporting service files:

```text
platform\cbcr_platform_pg\api.py
platform\cbcr_platform_pg\admin.py
platform\cbcr_platform_pg\runs.py
platform\cbcr_platform_pg\data_plane.py
platform\cbcr_platform_pg\risk_result_sets.py
platform\cbcr_platform_pg\case_selection.py
platform\cbcr_platform_pg\case_handoff.py
platform\cbcr_platform_pg\reports.py
platform\cbcr_platform_pg\lineage.py
platform\cbcr_platform_pg\bootstrap.py
```

The current UI is static HTML plus vanilla JavaScript and CSS, served by the FastAPI application. It is not a component framework application. The normal local URLs are:

```text
Application: http://127.0.0.1:8000/
Swagger:     http://127.0.0.1:8000/docs
```

Some development sessions use another port, such as `8011`; the code paths remain the same.

## 4. Current users and roles

The current bootstrap defines these internal roles:

- `platform_admin`: manages functions/catalogue, access, sources, and pipeline profiles;
- `dq_analyst`: runs DQ functions, sees DQ results, and manages DQ datasets;
- `risk_analyst`: runs risk functions, sees risk results, and manages risk datasets;
- `case_manager`: generates and reviews cases; and
- `auditor`: views the access/action audit.

The seeded `demo` user has the first four roles, including `platform_admin`. The seeded `auditor` user has the Auditor role only.

The header control labelled **Acting as** is not a role selector. It is a development/demo user-impersonation selector. The JavaScript inserts `demo`, `auditor`, and every user returned by the Users API into the dropdown.

An entry such as `acceptance-...` is a user created by an automated PostgreSQL acceptance test and left in the same database. It is not a third business role. Its appearance is therefore:

- test-data leakage into a user-facing environment;
- confusing because the control is presented as if it selects a role; and
- unsafe as a production authentication model.

Recommended correction:

1. In production, remove the **Acting as** selector and use the authenticated user identity.
2. Keep impersonation only behind an explicit development/demo feature flag.
3. Isolate acceptance tests in a separate test database and clean up test users.
4. Show the signed-in user's display name and effective roles in a profile menu.
5. Treat `platform_admin`, not `auditor`, as the high-privilege configuration role. Auditor should normally have broad read-only oversight rather than source/user administration rights.

For a simplified business presentation, the UI may show personas such as **Analyst**, **Case Reviewer**, **Auditor**, and **Administrator**, while retaining the existing many-to-many internal role model.

## 5. Recommended information architecture

### 5.1 Standard workflow interface

Use five normal primary-navigation entries:

1. **Home**
2. **Data lifecycle**
3. **Run history**
4. **Case workbench**
5. **Reports**

Show **Oversight** only to Auditor and Administrator users. Oversight contains lineage search and access/action audit.

Do not keep **Dataset workspace** as an empty primary-navigation destination. It should open contextually when the user selects a dataset from Data lifecycle, a run, a case, or a search result.

Move the following to a utility/profile/settings menu:

- Function reference/catalogue;
- Administration;
- API documentation;
- System status; and
- Advanced operations console.

### 5.2 Advanced interface

Retain the current nine-page interface, with the defects corrected, as **Advanced operations**. This is useful for developers, administrators, support staff, demonstrations, and uncommon investigative workflows.

The standard and advanced modes should use the same APIs and permission model. They should differ only in navigation, progressive disclosure, and workflow guidance. A route such as `/advanced` or a profile-menu command is clearer than making both sets of navigation visible simultaneously.

### 5.3 Naming note

Rename **Work queue**, but prefer **Home** or **Operations dashboard**, not **Landing Page**. “Landing” is already the name of a data zone, so using it for the application homepage would introduce a second meaning.

## 6. Shared interaction requirements

These changes apply across the whole UI.

### 6.1 Identifiers

Every Run ID, Dataset ID, Lot ID, Batch ID, Case-set ID, Risk-result-set ID, Evaluation ID, and Audit-case ID should use a reusable identifier component:

- initially show the short ID, for example `294835a6...`;
- clicking expands it in place to the complete ID;
- provide an adjacent **Copy** action;
- use a tooltip containing the full ID;
- retain the full ID in exported reports and detail panels; and
- allow direct search by a pasted full ID.

Do not make users navigate elsewhere merely to copy an identifier.

### 6.2 Filters and scale

List pages need server-backed filtering and pagination. Loading all data and filtering only in browser memory will not scale. Common filters should include:

- date range with sensible presets: Today, Last 7 days, Last 30 days, Custom;
- status;
- owner/initiating user, when permitted;
- lot/external reference;
- dataset ID;
- run ID;
- processing zone;
- function;
- purpose;
- report/entity identifier; and
- free-text search where appropriate.

Filters should be represented in the URL so a view can be bookmarked or shared.

### 6.3 Detail presentation

- Open row details as an inline accordion immediately below that row.
- Keep one row open by default, but permit multiple if comparison is useful.
- Provide explicit **Close** or collapse affordances.
- Render human-readable summaries first; place raw JSON under **Technical details**.
- Replace `window.prompt` interactions with labelled dialogs containing explanations, validation, Cancel, and confirmation.

### 6.4 Workflow guidance

- Display one clear primary action for the current stage.
- Explain prerequisites and why a disabled action is unavailable.
- Use a stage stepper showing completed, current, and future zones.
- Use breadcrumbs such as `Lot > Dataset > Run` or `Case set > Audit case`.
- Add contextual `i` help beside unfamiliar terms; do not rely on a separate manual alone.
- Use consistent terms everywhere: “risk-result set,” “selection batch,” “final case set,” and “audit handoff case.”

### 6.5 Role-aware behavior

Hiding controls is not sufficient security; APIs must enforce the same rule.

- Analyst: default to their own lots, datasets, and runs.
- Case Reviewer: see assigned/relevant candidate work and finalized sets.
- Auditor: read all relevant records and audit history; no operational mutation by default.
- Administrator: manage users, roles, sources, pipeline profiles, and function configuration.

## 7. Page-by-page manual, issues, and proposed changes

### 7.1 Header and application shell

#### Current behavior

- The system badge displays the persistence backend and database.
- **Acting as** changes the `x-cbcr-user` header and reloads visible data.
- **API Control Plane** opens Swagger.
- The sidebar exposes nine first-level pages.

#### Problems

- Technical health is overemphasized.
- User impersonation looks like role selection.
- Acceptance-test users can appear.
- Navigation reflects internal subsystems rather than user tasks.
- Users can see pages for which their role later receives `403 Forbidden`.

#### Required changes

- Replace **Acting as** with authenticated profile details.
- Put Swagger and advanced operations under a developer/help menu.
- Put system health under a small status icon with an expandable panel.
- Generate navigation from effective permissions.
- Do not show inaccessible pages and then rely on a later error.

### 7.2 Home / current Work queue

#### Current behavior

The page shows:

- backend, database, application user, and asynchronous-worker status;
- counts for active runs, canonical/DQ work, publication work, and risk-ready datasets;
- an Intake Lot button; and
- Recent Activity.

The code currently limits Recent Activity to the first six runs with `state.runs.slice(0, 6)`. It does not actually continue indefinitely. However, the heading **Runs requiring attention** is misleading because the code does not select only attention-requiring runs; it simply displays the first six returned runs of any status.

#### Proposed purpose

Make this a simple, role-specific operational dashboard answering:

1. What needs my attention?
2. What did I recently do?
3. Where is work accumulating?
4. What is the next action?

#### Required changes

- Rename to **Home** or **Operations dashboard**.
- Collapse technical health into **System status**.
- Collapse Recent Activity by default or show a small, meaningful list.
- Replace ambiguous counters with actionable cards:
  - My failed runs;
  - My active runs;
  - Datasets awaiting DQ gate;
  - Datasets awaiting enrichment/publication;
  - Risk runs awaiting evidence-set approval;
  - Candidate batches awaiting decisions.
- Add dashboard date presets and owner scope where permitted.
- Add modest dashboard reports:
  - runs by status over time;
  - lots/datasets by current zone;
  - DQ eligible versus rejected counts;
  - risk findings and case selections over time; and
  - median processing time between stages.
- Clicking a card must open a pre-filtered destination page.
- Avoid charts that do not lead to action.

#### Recent Activity filters

If retained, provide:

- date range;
- status;
- activity type: lot, dataset promotion, function run, risk-set approval, human decision, report generation;
- purpose/stage;
- initiated by: Me, All permitted users, a specific user;
- lot/dataset identifier; and
- “Requires action only.”

Use pagination or “View more,” and define the sort order visibly.

### 7.3 Intake Lot dialog

#### Current fields and meanings

**Source**  
Selects the configured adapter/database view from which canonical report-shaped data is read. This does not upload an XML file in the current dialog.

**Pipeline profile**  
Selects the permitted sequence of dataset zones and their storage bindings. If only one active profile is valid, there is no meaningful user choice.

**External lot reference**  
An optional business-friendly name/reference used to find the lot later. It should be encouraged because UUIDs are difficult to recognize.

**Report subset**  
An optional comma-separated list of exact report IDs. If empty, all reports exposed by the selected source are included. If populated, only matching report IDs are taken into the new lot. This is record selection, not a data-quality filter.

**Intake note**  
Free text stored in lot metadata to record the purpose or operator context.

**Create Lot**  
Creates the lot and both Landing and Canonical snapshots. The Landing snapshot preserves source-shaped payload records; the Canonical snapshot contains mapped canonical reports, entities, and metrics. The UI then opens the Canonical dataset workspace.

#### Required changes

- Hide Pipeline profile when only one option is available; show the selected profile in an expandable **Technical details** summary.
- If only one source is available, show it as read-only context rather than a dropdown.
- Rename Report subset to **Reports to include (optional)**.
- Replace the single text box with:
  - **All reports** (default);
  - **Select by report ID** with searchable multi-select/paste support; and eventually
  - **Select by criteria** where the source adapter supports period, reporting entity, jurisdiction, receipt date, message reference, or source batch.
- Show a preview count before submission: “4 of 10 available reports will be included.”
- Validate unknown/duplicate report IDs before creating the lot.
- Add inline help and a confirmation summary.
- Show progress and a durable result link after the asynchronous/intake action.

### 7.4 Data lifecycle

#### Current behavior

The page groups datasets by lot and lays the immutable datasets out as cards. Current filters are Lot and Zone.

**Zone does not mean Run ID.** It means the processing stage represented by a dataset snapshot:

- **Landing:** source-shaped records captured for the lot;
- **Canonical:** data mapped into stable CbCR API fields;
- **DQ passed:** records permitted through the configured DQ gate;
- **Enriched:** DQ-passed records plus optional governed enrichment facts, or an unchanged publication when enrichment is unnecessary;
- **Risk ready:** the final analytical snapshot on which risk functions run.

The label needs an `i` icon or persistent explanatory text.

#### Ownership observation

The database already records `cbcr_control.lot.received_by`, and datasets record `created_by`. Therefore, a new table is not required merely to identify who initiated a lot. However, the current List Lots and List Datasets APIs return all permitted records without enforcing an “own records only” policy. Proper row-level filtering must be implemented server-side.

#### Required changes

- Add filters for date range, owner, source, lot status, external lot reference, reporting period, zone, dataset status, report ID, dataset ID, and report count.
- Default Analyst users to **My lots**.
- Allow Auditor/Administrator users to select All users or an individual user.
- Render each lot as a collapsible timeline/funnel rather than an undifferentiated set of cards.
- Emphasize the latest/current stage while retaining access to earlier immutable snapshots.
- Show stage counts, timestamps, initiating user, and the next permitted action.
- Show concise reason text for missing stages, for example “DQ gate not yet evaluated.”
- Use a full-ID expansion/copy component.
- Add server-side pagination.

### 7.5 Dataset workspace

#### Current purpose

The workspace operates on one immutable dataset version. Current tabs are Overview, Data, Run functions, Results, Publish/enrich, and Governance.

#### Overview

Shows report/entity/metric counts and the next route stage, with shortcuts to Run Functions and Publishing.

Recommended changes:

- Add lot/external reference, owner, creation time, parent stage, and a stage stepper.
- Make the single recommended next action prominent.
- Put full technical identifiers behind expandable/copyable ID chips.

#### Data

Shows report ID, reporting entity, period, entity count, and metric count, with client-side text search.

Recommended changes:

- Add server-side pagination and filters.
- Allow report rows to expand into constituent entities and key metrics.
- Distinguish source data, canonical fields, and enrichment facts.
- Provide export only when authorized.

#### Run Functions

Shows only functions allowed for the current zone. A user selects functions and supplies function-specific parameters. All selected functions must have one purpose; the UI currently reports this rule only after selection.

Recommended changes:

- Group functions into **Recommended for this stage** and **Advanced/optional**.
- Show plain-language purpose, input fields, expected output, and examples beside each function.
- Disable incompatible functions as soon as a different purpose is selected.
- Add saved parameter presets and “Reset to defaults.”
- Show an execution summary before queuing: dataset, report count, functions, and parameters.
- Allow optional report/entity scope selection where supported.
- Link each function to contextual Function Reference details.

#### Results

The current workspace only remembers run IDs submitted during the current browser session in `state.workspaceRuns`. After refresh, older runs must be found in Run History.

Recommended changes:

- Load all authorized runs for this dataset from the server, not only session memory.
- Show status, function, findings, gate relevance, submitter, and timestamps.
- Expand details inline.
- Present “No findings” as a successful clean result, not an empty/error state.
- Keep raw result JSON under Technical details.

#### Publish / enrich

The content changes by zone:

- Canonical -> DQ passed: enter/select a completed DQ run, choose blocking severities, evaluate the gate, inspect report dispositions, then publish.
- DQ passed -> Enriched: optionally add one report- or entity-level enrichment fact with attribute, value, source reference, and confidence, or publish unchanged.
- Enriched -> Risk ready: provide a publication reason and create the next immutable snapshot.

Recommended changes:

- Rename dynamically: **Evaluate DQ gate**, **Enrich and publish**, or **Publish risk-ready**.
- Select eligible runs from a list; do not require pasting a Run ID.
- Explain blocking severities and show the expected inclusion/exclusion effect before publication.
- Support multiple enrichment facts in a reviewable grid, including delete/edit before submission.
- Make “Publish unchanged” explicit: enrichment is optional, but the governed snapshot transition may still be required by the selected profile.
- Add confirmation dialogs containing counts and lineage effect.

#### Governance tab

There is no Governance tab inside Run History in the current code. There is a Governance tab inside Dataset Workspace. If this is the tab considered unnecessary, hide it in standard mode and replace it with a **View lineage** secondary action or overflow-menu item. Keep it in advanced mode.

### 7.6 Run history

#### Current behavior

Current filters are Status and Purpose. Every row shows full Run ID, purpose, timestamp, status, and Inspect. Inspect places the detail panel at the bottom of the page, which makes the relationship to the selected row unclear.

#### Required changes

- Expand Inspect details immediately below the selected row and make them collapsible.
- Add filters for:
  - date range;
  - run status;
  - purpose;
  - function;
  - stage/input zone;
  - lot/external reference;
  - dataset ID/version;
  - initiating user;
  - report/entity ID;
  - findings present/absent;
  - maximum finding severity; and
  - active, completed, failed, or archived grouping.
- Add sortable columns for submitted, started, completed, duration, and finding count.
- Add a **My runs / All permitted runs** scope.
- Make every identifier expandable and copyable.
- Provide direct actions appropriate to the run, such as Open dataset, Evaluate DQ gate, Add to risk evidence set, or View lineage.
- Add pagination and URL-persisted filters.

### 7.7 Case workbench

#### Current functional sequence

The current page compresses four different business objects and several steps into one screen:

1. Select a published Risk-ready dataset.
2. Select one or more completed risk runs belonging to that dataset.
3. Give the collection a **Set name**.
4. Click **Create Draft Set**.
5. Review and approve the draft risk-result set.
6. Run `generate_case_candidates` against the same Risk-ready dataset, passing the approved risk-result-set ID.
7. That run creates a Selection Batch and candidate rows.
8. Open the Selection Batch and record Selected, Not selected, or Deferred plus rationale for each candidate.
9. Once all decisions are complete and at least one candidate is Selected, finalize the batch.
10. Finalization creates an immutable Final Case Set and individual Audit Handoff Cases.

#### Meaning of Set name

The Set name is the human-readable name of an immutable **risk evidence set** containing the exact risk-analysis runs chosen for downstream candidate generation. It is not a dataset, not a final case set, and not itself a report. A draft can be reviewed before approval; candidate generation must refer to the approved set.

#### Where the displayed objects come from

- **Approved risk-result sets:** created from selected completed risk runs.
- **Selection batches:** created by successful `generate_case_candidates` function runs using an approved risk-result set.
- **Candidate evidence & decisions:** candidate records within the selected batch, carrying source risk evidence and later human decisions.
- **Final case sets:** immutable collections produced when a completely reviewed batch is finalized.
- **Audit handoff cases:** one durable operational/audit record per selected candidate in the final case set.

#### Current problems

- All Risk-ready datasets are placed in one long selector.
- The user must understand and manually bridge risk set approval and candidate generation.
- “Create Draft Set” does not explain what is being drafted.
- Four object types are shown together without a stage relationship.
- Short IDs obscure provenance.
- Raw evidence JSON dominates candidate cards.
- Approval/finalization uses browser prompts.
- The page does not emphasize pending work or the next required action.

#### Required redesign

Use a guided stepper or master-detail workflow:

1. **Choose risk-ready dataset**
   - filter by date, owner, lot, external reference, reporting period, reporting entity, report count, and whether completed risk runs exist;
   - show only datasets relevant to the current user's scope by default.
2. **Review risk runs**
   - show functions, parameters, finding/result counts, date, submitter, and links to details;
   - permit selecting the exact runs to freeze.
3. **Create risk evidence set**
   - rename the button to **Create risk evidence set (draft)**;
   - relabel Set name to **Risk evidence set name**;
   - add an `i` explanation and a pre-creation summary.
4. **Approve evidence set**
   - show Draft -> Approved status and approval rationale;
   - use a proper modal.
5. **Generate candidates**
   - provide a contextual action directly on the approved evidence set;
   - automatically pass the risk-result-set ID to `generate_case_candidates` rather than asking the user to copy it into Run Functions;
   - expose candidate-generation thresholds in the same guided action.
6. **Review candidate batch**
   - show a batch header with source dataset, evidence set, generation run, thresholds, counts, owner, and status;
   - provide filters for Pending/Selected/Not selected/Deferred, score range, function, reason code, jurisdiction, entity, and report;
   - summarize evidence first and put raw JSON behind an expander;
   - support bulk decisions only with explicit rationale and authorization.
7. **Finalize case set**
   - show readiness checklist, selected count, unresolved decisions, and confirmation;
   - ask for final name and rationale in one dialog.
8. **Handoff and reports**
   - show the resulting Final Case Set and Audit Handoff Cases with direct Report and Lineage actions.

### 7.8 Final Reports

#### Current behavior

The page selects a finalized case set, automatically/explicitly generates two large reports, and provides CSV download and print actions:

1. selected cases; and
2. full dataset/run/function lineage.

#### Problems

- The selector lacks date, owner, dataset, status, or name search.
- Both reports occupy one continuous page with weak visual separation.
- The distinction between preview, report generation, download, and printing is unclear.
- The page does not first show a library of available finalized outputs.
- Large lineage tables and JSON parameters are difficult to scan.

#### Required redesign

- Start with a **Final case-set report library** containing filters for name, case-set ID, date range, finalized by, lot, dataset, reporting period, and selected-case count.
- Show a summary card/table row for each case set with **Open reports**.
- On open, show a report header containing case-set name, full/copyable ID, dataset, finalizer, finalization time, case count, and status.
- Use two clear tabs:
  - **Selected cases report**; and
  - **Processing and lineage report**.
- Add an Export menu: CSV, print/PDF-friendly view, and future structured output.
- Add search/filter within selected cases.
- Make case rows expandable into risk basis, source runs/functions, human decision, and handoff status.
- Present lineage as a stage timeline with expandable run/function tables.
- Keep effective parameters visible but collapse raw JSON.
- Add generated timestamp and filter criteria to printed/exported reports.
- Link back to the source Case Workbench, dataset, run, and lineage record.

### 7.9 Lineage and Audit / proposed Oversight

#### Current behavior

The page combines:

- end-to-end lineage for an Audit Handoff Case opened from Case Workbench;
- lineage for whichever dataset was most recently selected elsewhere; and
- the last 100 access/action audit events.

The page depends heavily on prior navigation state and provides no direct dataset/case selector.

**Access and action audit** records security and operational events such as who attempted an action, the action, target, time, and whether authorization was Allowed or Denied. A Denied audit record does not mean a taxpayer/case was rejected for audit; it means the application refused that user's attempted action under access control.

#### Required redesign

- Rename the Auditor-facing page **Oversight**.
- Split it into two tabs:
  - **Data and case lineage**; and
  - **Access and action audit**.
- Provide independent search selectors for Dataset ID, Lot ID, Run ID, Case-set ID, Audit-case ID, Report ID, or Entity ID. Do not rely on state selected on another page.
- Show lineage as a visual stage timeline; clicking a stage reveals promotions, runs, functions, parameters, findings, and user actions.
- Add audit filters for:
  - date/time range;
  - actor;
  - role;
  - action;
  - Allowed/Denied;
  - target type;
  - target reference;
  - stage/purpose; and
  - correlation/request ID if captured later.
- Add pagination and export for authorized auditors.
- Explain Allowed/Denied beside the filter.
- Keep audit data read-only.
- Permit deep links from runs, datasets, reports, and audit cases.

### 7.10 Function Catalogue

#### Functional purpose

The catalogue currently groups active functions by stage and displays function name, code, version, purpose, description, and parameter names. It helps users understand which independent controls exist and what parameters they accept. It is also useful for version/configuration governance and troubleshooting.

#### Recommendation

Keep it, but remove it from normal primary navigation.

- For Analysts, expose a read-only **Function Reference** under Help/Reference and link to the relevant entry from every function card.
- For Administrators, expose **Function configuration** under Settings, including activation, version, stage/purpose, schema, and lifecycle where supported.
- Add search/filter by stage, purpose, active state, parameter requirement, and name/code.
- Expand each function into plain-language inputs, outputs, examples, and applicable zones.
- Do not require users to visit the catalogue before running a normal stage; the essential explanation must remain contextual in Run Functions.

### 7.11 Administration

#### Current behavior

The page lists connected sources, users/roles, and pipeline profiles. Source endpoints can be changed. User and role APIs already exist, but the current UI only lists users and does not provide user creation or role assignment.

#### Recommendation

Remove Administration from primary navigation. Place it under a gear-shaped **Settings** menu visible only to `platform_admin`.

Use Settings sections:

1. **Users and access**
   - create user;
   - activate/deactivate user;
   - assign one or more roles;
   - show effective permissions;
   - inspect assignment history.
2. **Data sources**
   - view/edit endpoint references without displaying secrets;
   - test connection;
   - enable/disable source;
   - show last successful access.
3. **Pipeline profiles**
   - show route and storage bindings;
   - validate changes;
   - version rather than silently overwrite.
4. **Functions and mappings**
   - advanced configuration/reference, subject to existing APIs and future work.
5. **System status**
   - backend/database/worker details, migrations, and operational health.

Auditor may receive a read-only view of configuration history if required, but should not automatically receive Administrator mutation rights.

## 8. Additional issues identified from the current UI

1. **State is not deep-linkable.** Selected dataset, run, batch, and case are stored only in JavaScript memory. Refreshing loses context. Use route parameters.
2. **Workspace results are session-only.** Load dataset run history from the API.
3. **Cross-page dependency is hidden.** Governance depends on a previously selected dataset/case. Add direct selectors and URLs.
4. **All core data is fetched eagerly.** `refreshCore()` requests health, sources, profiles, functions, datasets, lots, runs, and users together. Fetch page-specific data and paginate it.
5. **Permission failures are silently converted to empty lists.** `safeTask(..., [])` can make “not authorized” look like “no data.” Distinguish Forbidden, unavailable, and genuinely empty.
6. **Raw JSON is overused.** Use summaries with optional technical expansion.
7. **Critical actions lack confirmation summaries.** Promotions, evidence approval, and finalization should show consequences and counts.
8. **Long-running actions have weak progress recovery.** Show durable queued/running state and allow returning later.
9. **Terminology is close but not fully consistent.** Maintain an in-app glossary.
10. **No responsive table strategy is evident.** Use column priority, horizontal scrolling, and detail drawers for smaller screens.
11. **Accessibility needs explicit treatment.** Provide keyboard operation, focus management for dialogs/accordions, visible focus, semantic labels, and non-color status cues.
12. **Encoding artefacts should be checked.** Some locally displayed source text shows mojibake characters for arrows/dashes; verify source encoding and HTTP charset.
13. **No standard empty-state next action.** Every empty state should say why it is empty and what the authorized user can do next.
14. **No saved views.** Frequent users would benefit from saved filters such as “My failed risk runs” or “Pending candidate decisions.”
15. **No notification/inbox model.** A lightweight task inbox would reduce reliance on users repeatedly checking multiple pages.

## 9. Proposed role-to-navigation matrix

| Surface | Analyst | Case Reviewer | Auditor | Administrator |
|---|---:|---:|---:|---:|
| Home | Yes | Yes | Yes | Yes |
| Data lifecycle | Own/permitted | Read relevant | Read all | Read all |
| Dataset workspace | Operate permitted stages | Read relevant | Read all | Read all |
| Run history | Own/permitted | Relevant case runs | Read all | Read all |
| Case workbench | If assigned role | Yes | Read-only if required | Yes/support |
| Reports | Permitted sets | Yes | Read all | Read all |
| Oversight: lineage | Contextual | Contextual | Yes | Yes |
| Oversight: access audit | No | No | Yes | Yes |
| Function Reference | Read | Read | Read | Read/manage configuration |
| Settings | No | No | Optional read-only | Manage |
| Advanced operations | Permission/feature flag | Permission/feature flag | Yes | Yes |

The exact business role model can be refined, but navigation must derive from effective permissions rather than hardcoded user names.

## 10. API/data implications of the UI proposal

Although this review focuses on the UI, several requested behaviors require backend support:

- server-side filtered/paginated lots, datasets, runs, audit events, case sets, and candidates;
- actor-aware “own records only” enforcement using `lot.received_by`, `dataset.created_by`, run creator, and case ownership fields;
- direct query APIs for dataset-specific historical runs;
- audit filtering beyond the current `limit` parameter;
- user activation/deactivation and role-assignment UI integration;
- optional dashboard aggregate endpoints rather than downloading entire tables;
- deep-link lookup by full ID and business references;
- an authenticated identity provider replacing arbitrary `x-cbcr-user` impersonation in production; and
- possibly assignment/team constructs if “own” must later include delegated or team work.

These should be documented as separate implementation requirements. The frontend must not simulate row-level security by hiding records already returned to the browser.

## 11. Suggested implementation sequence

1. Establish standard versus advanced navigation and permission-derived visibility.
2. Replace user impersonation in production and remove test-user leakage.
3. Build shared ID, filter, pagination, accordion, help, and confirmation-dialog components.
4. Redesign Home and Data lifecycle.
5. Make Dataset workspace context-driven and restore historical runs after refresh.
6. Redesign Run history with inline inspection and expanded filters.
7. Redesign Case workbench as the explicit risk-to-case stepper.
8. Redesign the Reports library and report viewer.
9. Split Oversight into Lineage and Access Audit with direct selectors.
10. Move Function Reference and Administration into utilities/Settings.
11. Preserve and test the existing interface as Advanced operations.
12. Add role-based usability and accessibility acceptance tests.

## 12. Acceptance criteria for the simplified UI

- A first-time Analyst can create a lot and reach Canonical workspace without understanding pipeline-profile internals.
- An Analyst can identify the next action for a dataset without consulting Swagger.
- A complete identifier can be expanded and copied wherever it appears.
- Refreshing or sharing a URL preserves dataset/run/case context.
- An Analyst sees only their permitted work; an Auditor can filter across users.
- Run inspection expands below the selected row.
- A user can explain the distinction between a risk-result set, selection batch, final case set, and audit handoff case from the on-screen text.
- Candidate generation can be initiated directly from an approved risk evidence set without manually copying its ID.
- Final reports are discoverable through a report library and clearly separated by report type.
- Lineage and security audit can be searched independently.
- “Denied” is never confused with a case-selection decision.
- Function Reference and Settings do not occupy normal primary navigation.
- The advanced interface remains available for exceptional operations and diagnostics.

## 13. Questions for the reviewing LLM/designer

Please comment specifically on:

1. Whether the five-item standard navigation is the right abstraction.
2. Whether Data lifecycle and Dataset workspace should be one routed feature or visually separate surfaces.
3. Whether the Case workbench is better represented as a stepper, kanban/work queue, or master-detail interface.
4. How best to present stage lineage without overwhelming ordinary Analysts.
5. Which dashboard aggregates are genuinely actionable and which should be omitted.
6. How to expose function parameters progressively while keeping expert operation efficient.
7. Whether Reports and Oversight should remain separate pages.
8. How the current vanilla HTML/JavaScript implementation should be refactored into reusable components without unnecessarily replacing the entire technology stack.
9. What responsive and accessibility patterns should be mandatory.
10. Which changes can be achieved only in the frontend and which should be paired with API/schema changes.

