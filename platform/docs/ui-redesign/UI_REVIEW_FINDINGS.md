# CbCR Control Plane — review of the running standard UI

**Reviewed:** 8 November 2026, `http://127.0.0.1:8011/` (standard UI: `web/standard.html`, `web/app/*.js`, `web/redesign.css`; API `cbcr_platform_pg/api.py`), as user `demo` at 1100 px and at the Claude pane width (~800 px).
**For:** the implementing LLM. Every finding names the file and the change. Severity: **Blocking** = wrong or impossible to use; **High** = contradicts the agreed design (`UI_REDESIGN_PROPOSAL.md`) in a way users will hit daily; **Medium** = polish/consistency; **Low** = nice to have.
**Companion:** `SCENARIO_WORKFLOWS.md` references these finding IDs.

**Relation to `IMPLEMENTATION_STATUS_AND_OPEN_ISSUES.md`:** that document was written without a browser (its §5 P2 says so). This review was done in a real browser against live data; it confirms its §5 items (P0 authentication = B-3 here; P1 intake preview = D-3; P2 administration depth = B-5; P2 run control = not re-raised) and adds the defects below, most of which are field-name mismatches and interaction bugs that only show up when the pages are actually used.

What is good and should stay: the router with real paths and refresh-safe state, `permissionError()` distinguishing 403 from empty, inline run inspection with auto-refresh, the five-step case flow with the evidence-set ID injected automatically, the two-tab report viewer with CSV/print, the dialog helper, and the overall fidelity to the existing look and feel.

---

## A. Shell: masthead, navigation, dropdown

| ID | Sev | Observed | Cause | Fix |
|---|---|---|---|---|
| **A-1** | High | A small bordered control labelled **OK** sits in the masthead and reads as a button ("an Ok button at the top"). It is the health status. | `shell.js` renders `<span class="health-pill ok">ok</span>`; `.health-pill` in `redesign.css` has a border + uppercase mono text, the same treatment as buttons. | Replace with the status-dot pattern: `<button class="status-dot ok" aria-haspopup="true" title="System status">PG · cbcr</button>` whose click opens a small panel with backend, database, worker and version (the data already in `state.health`). Use a coloured dot + the words *System OK / Degraded / Offline*, never a bare "OK". Move the *System and database details* expander off Home into this panel. |
| **A-2** | High | The user dropdown (**Demo multi-role user ▾**) does not close when you click elsewhere or press Esc; it only closes when a link inside it re-renders the shell. On narrow widths it can stay open over the content. | `<details class="profile-menu">` — native `<details>` has no outside-click or Esc behaviour. | Keep `<details>` but add one delegated listener in `shell.js`: `document.addEventListener('click', e => { document.querySelectorAll('details.profile-menu[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; }); });` and `keydown` Esc → `open=false`; also close it in `bindLinks` click handlers before navigating. Add `aria-expanded` on the summary. Alternatively use the `[data-menu]`/`.menu` pattern from the mockups (`mock.js` Part B). |
| **A-3** | Medium | The persona pill `ADMINISTRATOR` and the user name are two separate controls; the roles are only visible after opening the menu. | `shell.js` | Fold the persona into the profile button (`Demo multi-role user · Administrator ▾`) and list roles in the menu head. Hide the standalone pill. |
| **A-4** | Medium | No global "find by ID" box, although the lookup is wired (`bindGlobalLookup` listens for `[data-global-lookup]` but nothing renders it). | `shell.js` masthead template has no form. | Add `<form class="global-search" data-global-lookup role="search"><input name="value" placeholder="Find by ID or reference…"><output data-lookup-error></output></form>` to the masthead (hidden under 1100 px). |
| **A-5** | **Blocking** | In any dialog with required fields (Create user, Register source, Create evidence set, Approve…), **Cancel** and **×** do not close the dialog — the browser shows "Please fill out this field". Only Esc works. | `ui.js dialog()`: the cancel buttons are `<button value="cancel">` inside the form, so they are submit buttons subject to HTML validation. | Add `formnovalidate` (and `type="submit"` is fine) to both cancel buttons: `<button class="icon-button" value="cancel" formnovalidate aria-label="Close">×</button>`, `<button class="button-secondary" value="cancel" formnovalidate>Cancel</button>`. Also close on backdrop click (`element.addEventListener('click', e => { if (e.target === element) element.close(); })`). |
| **A-6** | Medium | Identifiers inside the workspace banner and the run-detail cards render in UPPER CASE (`497E375B…`, `6674E07C…`) and copying from the expanded chip is fine but the display is wrong. | `.workspace-banner span{text-transform:uppercase}` and `.detail-card span{text-transform:uppercase}` cascade into the chip's inner `<span>`. | Scope those rules to the label: `.workspace-banner > div > span:first-child`, `.detail-card > span:first-child`; and add `.id-chip span{text-transform:none}`. |
| **A-7** | Medium | Under 780 px the sidebar becomes a horizontal strip with a permanent scrollbar; the health pill stays while the persona pill disappears; the strip's two nav groups run into each other. | `.primary-nav,.utility-nav{display:flex;overflow:auto}` in the 780 px media query. | `scrollbar-width:none` + `::-webkit-scrollbar{display:none}` on the strip, `gap:4px`, a thin divider before the utility group, and hide `.health-pill` at 780 px (currently 520 px) once A-1 lands. |
| **A-8** | Medium | One click on an ID chip both expands it **and** copies to the clipboard with a toast — every exploratory click produces "Identifier copied". | `ui.js bindCommon()`. | Split: click toggles expand; a separate `⧉` button (already in the markup) copies. Keep `title` with the full ID. |

---

## B. Roles, scope and identity (navigation shows things the API refuses)

| ID | Sev | Observed | Cause | Fix |
|---|---|---|---|---|
| **B-1** | High | Home cards "Awaiting DQ gate: 19" and "Awaiting publication: 15" count every Canonical / DQ-passed / Enriched snapshot ever created, including ones already promoted. They are stage totals, not work. "Active runs" links to `status=running` and misses queued runs; "Awaiting publication" links to `zone=enriched` and misses DQ-passed. | `api.py dashboard()` counts by zone; `home.js card()` hrefs. | Count datasets that are the **latest snapshot of their lot** and have no successor: canonical with ≥1 completed DQ run and no `dq_passed` child → *awaiting DQ gate*; canonical with no completed DQ run → *awaiting DQ run*; `dq_passed`/`enriched` with no child → *awaiting publication*; `risk_ready` with completed risk runs and no approved evidence set → *awaiting evidence approval*. Link cards to `/lifecycle?awaiting=dq_gate` etc. and make the lifecycle page honour `awaiting`. Active runs → `/runs?status=queued,running` (accept comma lists). |
| **B-2** | High | Administrator (`demo`) sees **Oversight** in the sidebar, but *Access and action audit* answers "Permission required" (403). | `shell.js` shows Oversight for `auditor`/`platform_admin`; `bootstrap.py` grants `view_audit` to `auditor` only. | Decide one: either grant `platform_admin` `view_audit` (brief §4 argues auditor = read-only oversight, admin = configuration; an admin reading the audit log is reasonable), or render the *Access and action audit* tab only when `me.roles` includes `auditor`. Never show a tab that will 403. Same check for `/oversight/lineage`, which works for every role but is hidden from analysts — either show it to all (it only needs `view_datasets`) or keep it hidden consistently. |
| **B-3** | High (security) | Anyone is `demo` (Administrator) by default: `api.js` sends `localStorage.cbcr_actor || "demo"` and `api.py actor()` defaults to `"demo"`. | Deliberate dev shortcut. | Keep for dev only behind `CBCR_UI_IMPERSONATION=1`; in any other mode the API must take the user from the authenticated identity (reverse-proxy header / IdP) and `GET /me` must 401 when absent. Documented in proposal §7 A1. |
| **B-4** | High | Case Reviewer scope: Case workbench, Reports and the dashboard use `scope=me`, which means **lots received by me**. A reviewer who did not create the lot sees "No risk-ready datasets" and "No final reports yet". | `requested_owner()` keys everything on `lot.received_by`. | For `case_manager`, scope "me" should mean batches/case sets they own or that are assigned, or simply all risk-ready datasets with risk runs (`view_results` stage 07). Short term: when `me.roles` contains `case_manager` and not `dq_analyst/risk_analyst`, call the case endpoints with `scope=all` (the API already allows `broad` users; extend `broad_visibility()` to case managers for case objects). |
| **B-5** | Medium | `/settings/<anything other than sources>` silently shows *Users and roles*; the proposal's sections *Pipeline profiles*, *Functions and mappings*, *System status* are absent. | `settings.js` `section = sectionName==='sources' ? 'sources' : 'users'`. | Add the three sections (read-only tables are enough for v1: `GET /pipeline-profiles`, `GET /functions`, health) and 404 unknown sections. |

---

## C. Identity switching for demos and testing

| ID | Sev | Observed | Fix |
|---|---|---|---|
| **C-7** | Medium | There is no way to view the standard UI as another persona (needed for every scenario in `SCENARIO_WORKFLOWS.md`); testers must edit `localStorage` by hand. | When `CBCR_UI_IMPERSONATION=1` (exposed by `GET /health` or `/me`), render a **Viewing as** selector inside the profile menu listing `GET /users`; it writes `cbcr_actor` and reloads. Never render it otherwise. |

---

## D. Page-level findings

### Data lifecycle (`lifecycle.js`)

| ID | Sev | Observed | Fix |
|---|---|---|---|
| **D-1** | High | A flat list of 175 snapshot rows (one row per zone), not grouped by lot; no stage timeline; the user cannot see a lot's current stage or missing stages at a glance. | Group by `lot_id`: one `.lot-group` per lot with the five-stage strip (`.lot-stage` cards, mockup 02), the latest stage outlined, missing stages dashed with the reason, and the **next permitted action** on the header (logic in proposal §5.3). Keep the flat list as a "Snapshots" toggle if useful. |
| **D-2** | High | `page_size=250`, no pager, no sort control. | Server paging (`page`, `page_size=25`) and a `.pager`; sort by latest activity. |
| **D-3** | Medium | Intake dialog: no preview count, no validation of unknown/duplicate report IDs, textarea for IDs. | Add the All / By ID (searchable multi-select + paste) choice, preview "n of m reports", and validate before submit (proposal §5.3 A7). |
| **D-4** | Low | Lookup result for a lot routes to `/lifecycle?lot=<id>` but the page ignores `lot`. | Read `lot` in `lifecycle.js` filters (and pass to `GET /datasets?lot_id=`), or make the lookup route to `?q=<external ref>`. (Also D-25.) |

### Dataset workspace (`workspace.js`)

| ID | Sev | Observed | Fix |
|---|---|---|---|
| **D-5** | High | Page title is the bare zone name ("CANONICAL"); the lot reference appears nowhere on the page; no breadcrumb. | Title `FY2025-Q4-batch-01 · Canonical v1`; breadcrumb `Data lifecycle › <lot ref> › Canonical v1`; add `external_lot_ref` to `GET /datasets/{id}/versions/{v}` (it is already on the list endpoint) and show *Lot* + *Parent snapshot* in the banner. |
| **D-6** | **Blocking** | Data tab shows "—" for Period and Jurisdictions on every row. | The API returns `reporting_period_end`, `reporting_entity_name`, `entities[]`, `metrics[]`; the code reads `r.reporting_period||r.period_end`, `r.jurisdictions`. Use `reporting_period_end`, `entities.length`, `metrics.length`, and `new Set(metrics.map(m=>m.jurisdiction)).size`. Make rows expandable into the entity table rather than a raw JSON *View*. |
| **D-7** | Medium | Run functions: parameters always expanded; no *Recommended / Advanced* grouping; boolean parameters (`require_tin`) are text inputs containing `true`; array parameters are plain text. | Collapse behind "Show parameters (n)"; group by stage per proposal §5.4; render `boolean` as a checkbox, `array` as a comma list with a hint, `integer/number` with `step`. |
| **D-8** | Low | Ticking a function does not highlight the card. | `.function-card.selected` exists in CSS; toggle it on `change`. |
| **D-9** | High | No pre-queue summary and no confirmation for Queue / Publish; the publish button performs *evaluate + promote* in one click. | Use `confirmAction()`/`dialog()` with a summary table (dataset, functions, parameters / source → target, counts, reason) before every mutation. |
| **D-10** | Medium | Results tab "Inspect" leaves the workspace for `/runs/:id`. | Expand inline (`.run-card` + body) and keep the Run-history link as secondary. |
| **D-12** | **Blocking** (data) | "Requested" shows "—" on Home and in the workspace Results tab. | Runs carry `created_at` (and `started_at`, `completed_at`), not `requested_at`. `runs.js` already falls back; fix `home.js` and `workspace.js` (`r.requested_at||r.created_at`), and show duration = `completed_at − started_at`. |
| **D-13** | High | Every tab switch re-fetches dataset, reports, functions, runs and profiles (~3 s per click; the reports call is the slow one). | Fetch once per dataset/version, cache in module state keyed by `datasetId:version`, re-render tabs from cache; fetch `reports` lazily on the Data tab; keep the `Loading…` state local to the tab. |
| **D-14** | High | DQ gate: the dispositions (eligible/rejected per report, reason codes) are never shown; the user publishes blind. The run selector lists runs by raw UUID. | Two steps: **Evaluate gate** → render `GET /evaluations/{id}/dispositions` as the preview (eligible / rejected / warnings kept + per-report table), then **Publish DQ-passed** behind a confirmation. Label runs in the selector as `ab12cd34… · completed 09:48 · 4 functions · 2 warnings`. Rename the tab per transition (*Evaluate DQ gate*, *Enrich & publish*, *Publish risk-ready*). |
| **D-15** | **Blocking** | Lineage tab always says "No lineage events". | `GET /datasets/{id}/versions/{v}/lineage` returns `{dataset:{…, parents:[…]}, promotions:[…]}`, not an array; `rows.length` is undefined. Render `dataset.parents` + `promotions` as the vertical timeline (mockup 03 › Lineage). |
| **D-16** | Medium | Enrichment: a single attribute per publication; no reviewable grid; "publish unchanged" is implicit. | Grid with add/edit/remove rows (the API accepts a list) and two explicit buttons: *Publish unchanged* / *Add n facts & publish*. |
| **D-17** | High | Risk functions that depend on earlier runs (`load_domestic_risk_context.screening_run_id`, `analyze_outbound_low_substance_payments.domestic_context_id`, `analyze_interest_stripping.domestic_context_id`) make the user copy UUIDs from one run into another's parameter box. | Render these parameters as selects: `screening_run_id` ← completed runs on this dataset that include `analyze_profit_presence_mismatch`; `domestic_context_id` ← artifacts of completed `load_domestic_risk_context` runs (`function_runs[].artifacts[].domestic_context_id`). Same pattern as `risk_result_set_id` in the old `inputFor()`. |

### Run history (`runs.js`)

| ID | Sev | Observed | Fix |
|---|---|---|---|
| **D-11** | Medium | No lot/external-reference column (the run summary already has `external_lot_ref`); raw JSON (`parameters`, `result_summary`, `artifacts`, `evidence`) is inline rather than behind *Technical details*; dates wrap to three lines. | Add a Lot column; readable key/values first and `technical(jsonBlock(...))` after; `white-space:nowrap` on the date column; add server paging (184 rows now). |

### Case workbench (`cases.js`)

| ID | Sev | Observed | Fix |
|---|---|---|---|
| **D-18** | High | The dataset chooser gives no sign of progress (which datasets have evidence sets, open batches, finalised sets). | Add the progress bar + status line per row (mockup 05 `.work-item`): "Step 4 · 5 of 12 pending", "Finalised 28 Oct". The data is already loaded (`resultSets`, `batches`, `caseSets`). |
| **D-19** | **Blocking** (data) | Saved rationales are not shown when revisiting a batch; decided-by/at never shown. | The API field is `decision_rationale` (plus `decided_by`, `decided_at`); the code reads `c.rationale`. Show "Decided by r.mehta · 5 Nov 18:40 — rationale" on decided cards and collapse their controls behind *Change decision*. |
| **D-20** | High | In a **finalised** batch the Select / Do not select / Defer buttons and the rationale box are still active (the API will refuse, but the UI invites it). The batch header does not show the batch status. | Pass `batch.status` to `candidateCard`; render read-only when not `open`; add a `.batch-header` (batch, evidence set, generation run, thresholds, decision counts, status). |
| **D-21** | High | Step 5 has no readiness checklist; the user discovers "pending decisions remain" only from the API toast. Step labels in the stepper are not clickable. | Checklist (all decided ✓/✕ with the pending count, ≥1 selected, batch open, role) and disable the button with the reason; make stepper items links to `/cases/:id/v:ver/:n`. |
| D-26 | Medium | Step 4 defaults to `batches[0]` when no `?batch=` — not necessarily the open one. | Prefer the most recent `open` batch; list others. |
| D-27 | Low | Create-evidence-set dialog lists runs as raw UUIDs. | Use the same labelled format as D-14. |

### Reports (`reports.js`)

| ID | Sev | Observed | Fix |
|---|---|---|---|
| **D-22** | Medium | Library has no filters/search; five rows named identically ("Acceptance final audit cases"). | Name/ID search, date range, finalised-by; show lot reference and dataset per row. |
| **D-23** | Low | Score prints as `25.00000000`. | `Number(c.score).toFixed(2)` (or locale format). |
| D-28 | Low | Selected-cases rows are not expandable; evidence is a raw JSON expander. | Accordion row with risk basis (rule, evidence key/values, source run chip), decision block, handoff block; JSON under *Technical details*. |

### Oversight (`oversight.js`)

| ID | Sev | Observed | Fix |
|---|---|---|---|
| **D-24** | High | Audit-case lineage is dumped as one JSON block. | Render the stage timeline (source XML → lot → snapshots → gate → risk → evidence/candidates → decision/handoff) from `dataset_ancestry`, `source_risk_results`, `decision_history`, `audit_case_events`, `source_document` (mockup 07). |
| **D-25** | Medium | Lookup of an external lot reference → "Open context" → unfiltered lifecycle list (`?lot=` ignored). Short IDs and report IDs are "not found" with no hint. | See D-4; add "Enter the complete identifier (36 characters) or an external lot reference" to the 404 message; consider prefix matching on the server when unique. |
| D-29 | Low | Audit table: target column shows raw `resource`; no stage/purpose column; `limit=250` without paging. | Show target type + chip; add paging; keep the Allowed/Denied legend (good). |

---

## E. Content and data hygiene

| ID | Sev | Observed | Fix |
|---|---|---|---|
| **E-1** | High | Test data leaks into every list: users `acceptance-<uuid>` (three of them, all *Active*), lots `implicit-run-<uuid>` and `pg-acceptance-<uuid>`, functions `acceptance_<hex>` (retired), evidence sets "Acceptance evidence …". | Run acceptance tests against a separate database (proposal §7 A13) and clean up after each run; add a one-off cleanup script; until then, hide `acceptance-*` users by default in Settings with a "Show test users" toggle and a warning callout. |
| **E-5** | Medium | Function reference lists retired functions (`?lifecycle=` → all). | Default to `lifecycle=active`; add a *Show retired* toggle. |
| **E-6** | Low | Role descriptions are empty in the Create/Edit user dialog ("Auditor —"). | Seed `description` in `bootstrap.py` roles (and return it from `GET /roles`), or map in the UI: dq_analyst "Run DQ functions, see DQ results, manage DQ datasets", etc. |
| E-7 | Low | Function descriptions are developer prose ("Plans currency normalisation without physical column knowledge", "Assesses deterministic entity-link readiness"); "Output classification: restricted" is meaningless to users. | Use `docs/FUNCTION_CATALOGUE_PLAIN_LANGUAGE.md` for a plain-language description per code and hide *Output classification* unless it carries a real value. |
| E-8 | Low | Home card label "Pending case decisions" counts across all batches (including abandoned test batches). | Count only candidates in `open` batches. |

---

## F. Accessibility and responsive

| ID | Sev | Observed | Fix |
|---|---|---|---|
| F-1 | Medium | Profile `<summary>` has no `aria-expanded`; the health pill has no accessible name beyond "ok". | Add `aria-expanded`, `aria-label="System status: OK"`. |
| F-2 | Medium | Dialogs: initial focus is not placed on the first field; closing does not return focus to the opener. | In `dialog()`: focus the first `input,select,textarea` after `showModal()`; store `document.activeElement` and restore on close. |
| F-3 | Low | Status chips rely on colour + tiny 9 px mono text. | Minimum 10 px; keep the text label (already present). |
| F-4 | Low | `<main aria-live="polite">` announces the whole page on every render. | Remove `aria-live` from `main`; announce route changes with a visually hidden status element instead. |
| F-5 | Low | Tables have no column-priority rules under 780 px; wide tables scroll inside `.table-wrap` (acceptable) but the `.dataset-row` hides owner/reports columns with no way to see them. | Rely on the accordion/detail for hidden columns; keep horizontal scroll inside tables only. |

---

## G. Suggested fix order

1. **Blocking:** A-5 (dialog cancel), D-6 (Data tab fields), D-12 (dates), D-15 (lineage shape), D-19 (rationale field).
2. **Shell:** A-1, A-2, A-6, A-8, A-7.
3. **Role/scope consistency:** B-2, B-4, B-1, C-7 (dev-only persona switch), B-5.
4. **Workflow guidance:** D-14 (gate preview + confirmations), D-9, D-17 (dependent-parameter selects), D-20/D-21 (review/finalise), D-18.
5. **Lifecycle redesign:** D-1, D-2, D-5, D-13.
6. **Content:** E-1 (test data), E-5, E-6, E-7, D-24, D-22/23.
7. **A11y/responsive:** F-1…F-5.

Acceptance: re-run `SCENARIO_WORKFLOWS.md` S0–S8; every ⚠ step should pass without the marker.
