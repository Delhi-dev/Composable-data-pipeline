# CbCR Workbench — Simplified UI: design proposal and implementation hand-off

**Status:** Implemented in the PostgreSQL control plane on 6 November 2026. See `IMPLEMENTATION_STATUS_AND_OPEN_ISSUES.md` for verification, deliberate deviations and remaining production work.
**Prepared:** 6 November 2026
**Responds to:** `docs/UI_SIMPLIFICATION_AND_REDESIGN_BRIEF.md` (the "brief")
**Audience:** the LLM/engineer implementing the redesign in `platform/cbcr_platform/web/`

---

## 0. What is in this package

```
platform/docs/ui-redesign/
├── UI_REDESIGN_PROPOSAL.md          ← this document
└── mockups/
    ├── 00-index.html                ← start here: links every mockup, persona/theme switcher
    ├── 01-home.html                 ← Home (replaces Work queue)
    ├── 02-lifecycle.html            ← Data lifecycle + redesigned Intake lot dialog (#intake)
    ├── 03-workspace.html            ← Dataset workspace (contextual, routed) incl. DQ-gate variant
    ├── 04-runs.html                 ← Run history with inline inspection
    ├── 05-cases.html                ← Case workbench as master–detail + 6-step flow
    ├── 06-reports.html              ← Reports library + two-tab viewer
    ├── 07-oversight.html            ← Oversight (lineage lookup + access/action audit)
    ├── 08-settings.html             ← Settings (replaces Administration)
    ├── 09-function-reference.html   ← Function reference (replaces Function catalogue in nav)
    ├── base-niche.css               ← VERBATIM copy of web/niche.css   (do not edit; reference only)
    ├── base-wip.css                 ← VERBATIM copy of web/wip-workbench.css (same)
    ├── base-reports.css             ← VERBATIM copy of web/reports.css (same)
    ├── redesign.css                 ← NEW component styles — the stylesheet to port into web/
    └── mock.js                      ← shell renderer + widget behaviours (port) + mock-only persona/theme switcher (do not port)
```

Open `mockups/00-index.html` in a browser (plain `file://` works; no build step). The yellow **MOCKUP** bar at the bottom-left switches the viewing persona (Analyst, Case Reviewer, Auditor, Administrator) and the theme (default "WIP" Courier theme, or the "polished" Niche theme). Both themes are the product's own stylesheets, untouched; `redesign.css` only adds classes. **The look and feel is deliberately unchanged** — only navigation, page composition, disclosure and workflow guidance change.

Everything in the mockups is static. Counts, IDs and names are illustrative but internally consistent across pages (the same lots, datasets, runs and case set reappear), so the mockups can be read as one end-to-end story: lot `FY2024-Q3-batch-03` is at *DQ passed* awaiting enrichment; lot `FY2024-Q2-batch-02` is at *Risk ready* with an approved evidence set and an open candidate batch; lot `FY2024-Q1-batch-01` has been finalised into case set *Audit handoff 2026-10-28*; lot `demo-20260821-01` has a failed DQ run.

---

## 1. Summary of the recommendation

1. **Keep the existing visual language and the vanilla HTML/JS/CSS stack.** No framework. Refactor `niche.js` into a small router plus per-page modules and a handful of reusable rendering helpers (§8).
2. **Five primary navigation entries** — Home, Data lifecycle, Run history, Case workbench, Reports — plus **Oversight** for Auditor/Administrator. Dataset workspace becomes a *routed, contextual* surface opened from a lot stage, a run, a case or a search result. Function reference, Settings, Advanced operations and API docs move to a **Utilities** block in the sidebar and to the profile menu (§3).
3. **Navigation and in-page controls derive from effective roles** returned for the authenticated user. The "Acting as" impersonation box disappears from the standard UI (kept behind a dev flag in Advanced operations).
4. **Seven shared components** carry most of the simplification: ID chip, stage stepper, filter bar with URL mirror, accordion rows, next-action panel, confirmation dialog, technical-details expander (§4). They are specified as HTML contracts in `redesign.css`/`mock.js` so they can be ported directly.
5. **Every state is a URL**: `/datasets/:id/v:version/:tab`, `/runs?…`, `/cases/:datasetId/:step`, `/reports/:caseSetId/:tab`, `/oversight/lineage?case=…`. Refresh and share work (§3.3).
6. **Nothing is deleted.** Everything that leaves the standard navigation is still reachable: either contextually (lineage, technical details, Swagger) or under Utilities/Settings, or in **Advanced operations** = the current nine-page UI, behind `/advanced` and a permission/feature flag (§6).
7. Several requested behaviours need API work; they are listed with the frontend changes they unblock (§7) so the two can be sequenced.

---

## 2. Answers to the brief's questions (§13 of the brief)

**Q1 — Is five-item standard navigation right?** Yes, with one refinement: order them in workflow order (Home → Data lifecycle → Run history → Case workbench → Reports) and group them under a visible "Workflow" label, with "Oversight" as a second labelled group visible only to Auditor/Admin. Run history stays a top-level entry (not folded into Home) because analysts search across datasets by status/function, which no other page serves. The numeric prefixes `01…` are kept for continuity with the current sidebar.

**Q2 — Data lifecycle and Dataset workspace: one routed feature or two surfaces?** One routed feature, two views. The lifecycle list is `/lifecycle`; opening any stage goes to `/datasets/:id/v:version/:tab` and highlights the *Data lifecycle* nav entry, with a breadcrumb `Data lifecycle › <lot> › <zone v>` back to the list. The current empty "Select a dataset" page is removed. Mockup 03 shows the workspace; the banner, breadcrumb and stage stepper are the glue.

**Q3 — Case workbench: stepper, kanban or master–detail?** Master–detail with a guided stepper inside the detail (mockup 05). The left list is one entry per risk-ready dataset that has case work ("case pipeline"), each with a 6-segment progress bar and a one-line status. The right side is the selected pipeline's six steps (Dataset → Risk runs → Evidence set → Candidates → Review → Finalise). A pure stepper hides parallel work; a kanban hides the strict ordering the API enforces. Master–detail does both. Step 4 ("Generate candidates") is the contextual action that passes `risk_result_set_id` automatically.

**Q4 — Lineage without overwhelming analysts.** Three levels: (a) the stage stepper on every workspace banner (always visible, no detail); (b) a vertical *timeline* per stage with collapsed bodies (Dataset workspace › More › View lineage, Reports › Processing & lineage); (c) the full Oversight trace with raw JSON behind "Technical details". Analysts only ever see (a) and, on request, (b).

**Q5 — Which dashboard aggregates are actionable?** Keep exactly the six attention cards (my failed runs, my active runs, awaiting DQ gate, awaiting enrichment/publication, risk runs awaiting evidence approval, candidate batches awaiting decisions) — each is a link to a pre-filtered page. Keep three small reports because each has a click-through: lots by current stage, runs by status (30 d), median time between stages (plus the DQ eligible/rejected ratio). Omit anything without a destination (e.g. findings per severity over time), and omit charts in favour of simple bar rows.

**Q6 — Function parameters, progressive but efficient.** Group cards into *Recommended for this stage* and *Advanced/optional*; parameters are collapsed behind "Show parameters (n)" with defaults pre-filled, a preset selector and "Reset to defaults"; a *purpose lock* disables incompatible cards the moment a box is ticked; a pre-queue summary lists dataset, scope, functions and parameters. Expert users tick boxes and press Queue without opening anything. Each card links to its Function reference entry.

**Q7 — Reports and Oversight: separate pages?** Yes. Reports is a *business output* page (library of finalised case sets, two report tabs, export). Oversight is a *control* page (trace anything by ID; security audit). They link to each other (the lineage report tab offers "Full lineage"; Oversight offers "Full lineage report") but merging them would put security audit in front of Case Reviewers.

**Q8 — Refactoring vanilla JS into components.** Keep the stack. Split `niche.js` (single 51 KB file, single global `state`, all pages rendered eagerly) into: `app/router.js` (hash or History routes → page module), `app/api.js` (fetch with auth and a `Forbidden` error type), `app/components.js` (`idChip`, `stepper`, `filterBar`, `accordionTable`, `confirmDialog`, `techDetails`, `emptyState`), `app/shell.js` (masthead + nav from `/me`), and one module per page under `app/pages/`. Keep string-template rendering and event delegation (as `mock.js` does) — no virtual DOM needed. Details in §8.

**Q9 — Mandatory responsive and accessibility patterns.** (1) Column-priority tables: `.data-table` hides lower-priority columns under 1050 px and relies on the accordion row for detail; (2) horizontal scroll only inside `.table-wrap`, `.stepper`, `.lot-stage-list`; (3) sidebar collapses to a horizontal tab strip under 780 px (already in niche.css — but see defect §9.1); (4) all dialogs are native `<dialog>` with focus trap, `Esc` to close and a labelled close button; (5) accordion triggers are `<button aria-expanded>`; (6) status is never colour-only (text label inside `.status`); (7) visible focus (already in niche.css); (8) ID chips are buttons with `aria-label`; (9) `prefers-reduced-motion` respected for the toast transition.

**Q10 — Frontend-only vs API/schema.** See §7. Roughly: shell, navigation, ID chips, steppers, accordions, dialogs, grouping, naming, confirmation summaries, hash routing and the Function reference are frontend-only. Scoping ("mine"), server-side filters/pagination, dataset-run history after refresh, audit filters, user management and dashboard aggregates need API work.

---

## 3. Information architecture

### 3.1 Primary navigation (sidebar)

| # | Entry | Route | Visible to |
|---|---|---|---|
| | *Workflow* (section label) | | |
| 01 | Home | `/` | all |
| 02 | Data lifecycle | `/lifecycle` | all (scope differs) |
| 03 | Run history | `/runs` | all (scope differs) |
| 04 | Case workbench | `/cases` | case_manager, risk_analyst, platform_admin; auditor read-only |
| 05 | Reports | `/reports` | all (scope differs) |
| | *Oversight* (section label) | | auditor, platform_admin |
| 06 | Lineage & audit | `/oversight` | auditor, platform_admin |
| | *Utilities* (sidebar footer + profile menu) | | |
| | Function reference | `/reference` | all |
| | Settings | `/settings` | platform_admin |
| | Advanced operations | `/advanced` | platform_admin, auditor, or feature flag |
| | API documentation ↗ | `/docs` | platform_admin |

Badges on nav items (e.g. "1" on Case workbench) come from the same aggregate endpoint as the Home cards.

### 3.2 Masthead

Brand · **global find box** (paste any full ID or external reference → resolves to lot/dataset/run/batch/case set/audit case and routes there) · **status dot** (`PG · cbcr`; click expands backend/database/app user/workers/migrations) · **profile menu** (display name, persona, roles; Utilities links; Sign out). The "Acting as" selector and the "API CONTROL PLANE" link are removed from the standard shell.

### 3.3 Routes (deep-linkable state)

```
/                                  Home                      ?period=7d&scope=me
/lifecycle                         Data lifecycle            ?scope=me&period=30d&zone=&q=&page=
/datasets/:id/v:ver/:tab           Dataset workspace         tab ∈ overview|data|functions|results|publish|lineage|technical
/runs                              Run history               ?scope=&status=&purpose=&function=&zone=&lot=&dataset=&q=&sort=&page=
/runs/:runId                       Run history with that row expanded
/cases                             Case workbench            (list; auto-selects the most recent pipeline)
/cases/:datasetId/v:ver/:step      step ∈ dataset|runs|evidence|candidates|review|finalize
/reports                           Library
/reports/:caseSetId/:tab           tab ∈ cases|lineage
/oversight/lineage?case=|dataset=|run=|lot=|report=|entity=
/oversight/audit?period=&actor=&role=&action=&outcome=&target=&page=
/reference[#function_code]
/settings/:section                 section ∈ users|sources|profiles|functions|system
/advanced                          the current UI (index.html as-is, with defects fixed)
```

The mockups use `#hash` for tabs/steps because they are static files; the product should use the History API with the same paths (hash fallback is acceptable if the FastAPI static mount cannot serve `index.html` for all paths — then prefix with `#/`).

---

## 4. Shared components (port from `redesign.css` + `mock.js` Part B)

Each component is a small HTML contract plus a delegated event handler. Class names below are the ones in `redesign.css`.

| Component | Markup contract | Behaviour | Where used |
|---|---|---|---|
| **ID chip** `.id-chip` | `<button class="id-chip" data-id="FULL" title="FULL"><span class="kind">run</span><span class="short">294835a6…</span><span class="full">FULL</span><span class="copy">COPY</span></button>` (helper `idChip(kind, full)`) | click toggles `.open` (short ↔ full); click on COPY copies + toast; tooltip holds full ID | every Run/Dataset/Lot/Batch/Case-set/Evidence-set/Evaluation/Audit-case ID, everywhere |
| **Stage stepper** `.stepper > .step` | `.step.done|.current|.future|.blocked|.skipped` with `<strong>` + `<small>`; optional `.clickable[data-step]` | purely presentational unless clickable; `.vstepper/.vstep` vertical variant | workspace banner, lot timelines (as `.lot-stage` cards), case workbench, oversight |
| **Filter bar** `.panel.filter-bar` | `label` fields, `.segmented` scope control, `.actions` (More filters / Apply), `.filter-more[hidden]`, `.chips` with `.chip` (active filters) and `.chip.url` (URL mirror) | Apply builds the query string, pushes History state and refetches; chips remove a filter | Home, Lifecycle, Runs, Reports, Oversight, Settings |
| **Accordion table** `.data-table` | `tr.summary` followed by `tr.row-detail[hidden] > td[colspan]`; chevron `button.chevron` | click on the summary row (outside links/inputs) toggles the detail; `.open` on the row; `data-toggle="next"` for explicit buttons | Runs, Data tab, Reports, Settings users |
| **Run card / timeline item** `.run-card`, `.tl-item` | `.top` / `.tl-head` + `.body` / `.tl-body[hidden]` | same toggle behaviour as accordion rows | Results tab, Case workbench, Reports lineage, Oversight |
| **Next-action panel** `.next-action` | title, explanation, `ul.checklist` of prerequisites (`li.ok|.bad`), one `.command` | the single recommended action; disabled commands carry a `title` with the reason | Workspace overview |
| **Callout / empty state** `.callout[.ok|.warn|.danger]`, `.empty-state` | strong + text; empty state has "why" + next action | — | all pages |
| **Help icon** `.help` | `<span class="help" title="…">i</span>` | native tooltip (upgrade to a popover for touch later) | beside every unfamiliar term: zone, blocking severity, risk evidence set, Allowed/Denied |
| **Confirmation dialog** `dialog` + `.summary-table` | `<dialog><form method="dialog">` with `.dialog-head`, summary table, rationale input, `.dialog-actions` | `showModal()`; Cancel is `value="cancel"`; Confirm posts | publish, evaluate gate, approve evidence set, bulk decision, finalise, create user, edit source |
| **Technical details** `details.tech-details` | `<details class="tech-details"><summary>Technical details</summary><pre>…</pre></details>` | native | wherever raw JSON used to be inline |
| **Menu** `[data-menu="id"]` + `.menu#id[hidden]` | button + absolutely positioned panel | opens/closes; click-outside closes; `aria-expanded` | profile, status, overflow tabs, export |
| **Segmented control** `.segmented` | buttons; `.active` | single-select | scope, date presets, decision filter |
| **Pager** `.pager` | count text + `.pages` buttons | server-side paging | lists |

Rules that apply across components: human-readable summary first, raw JSON only inside `.tech-details`; "No findings" renders as a `.callout.ok` *clean result*, never as an empty state; every disabled primary action explains why (title or adjacent `.why`); every empty state says what to do next; identifiers are never shown as bare `code` outside exports.

---

## 5. Page-by-page specification

For each page: what the mockup shows, what changes relative to the current code, and what it needs from the API (⚙ = API dependency, see §7).

### 5.1 Shell (`index.html`, `renderShell` in `niche.js`)

* Replace the static `<nav>` with navigation rendered from the authenticated user's roles (⚙ `GET /me` → `{user_id, display_name, roles[]}`; until it exists, derive from `GET /users` filtered to the request user). Pages a role cannot open are not rendered at all.
* Remove `#actor` from the standard shell. Keep impersonation only inside `/advanced` behind `CBCR_UI_IMPERSONATION=1` (dev/demo).
* Move the health panel into the status dot; the four health cells stay as a `dl.kv` inside the menu (`renderShell` already has the data).
* Add the global find box: on submit, try the ID against lots, datasets, runs, risk-result sets, batches, case sets and audit cases (⚙ ideally `GET /lookup?id=` ; interim: parallel `GET`s) and route to the matching page.
* Drop the eager `refreshCore()`; each page module fetches what it shows (§8).

### 5.2 Home (`01-home.html`; replaces Work queue)

* Scope row: period preset (Today / 7 d / 30 d / Custom) and owner scope (Mine default; All permitted / specific user for Auditor and Admin).
* Six attention cards, each a link to a filtered route; counts come from ⚙ `GET /dashboard?period=&scope=` (interim: compute client-side from `/runs`, `/datasets`, `/risk-result-sets`, `/selection-batches` as `renderWork` does now, but with correct predicates — the current "Runs requiring attention" heading is wrong: `state.runs.slice(0,6)` is simply the first six runs).
* Recent activity: filters (type, status, requires-action), fixed sort "newest first", paged "View more". Rows use ID chips and link to the object.
* Three bar reports and the median-time key/values, each clickable. No chart library.
* `+ INTAKE LOT` opens the intake dialog (routes to `/lifecycle#intake`).

### 5.3 Data lifecycle + Intake dialog (`02-lifecycle.html`)

* Filter bar: scope (My lots default; All/User for Auditor/Admin ⚙), period, free-text find, current stage (with `i` explaining zones), lot status; More filters: source, reporting period, dataset status, report count, report ID, dataset ID. Active-filter chips, URL mirror, server-side pagination ⚙.
* Each lot = `.lot-group` with a collapsible header (name, lot ID chip, received by `lot.received_by`, received at, report count, source, current stage, **next permitted action** button) and a `.lot-stage-list` of five `.lot-stage` cards in profile order. Existing snapshots show zone, dataset chip, version/report count, created by/at, run summary and OPEN; the latest gets `.latest` (outlined) and the primary OPEN WORKSPACE; missing stages are dashed with a reason ("DQ gate not yet evaluated", "Requires an Enriched snapshot (profile …)", "Not in this pipeline profile" for skipped zones). Current `datasetCard()`/`renderLifecycle()` are replaced by `renderLot(lot, datasets, profile, runsByDataset)`.
* Next-action logic (frontend): canonical with no completed DQ run → "Run DQ functions"; canonical with completed DQ run and no gate evaluation → "Evaluate DQ gate"; dq_passed → "Enrich & publish" (or "Publish risk-ready" if the profile skips enriched); enriched → "Publish risk-ready"; risk_ready → "Run risk functions" / "Case workbench"; last DQ run failed → "Re-run DQ functions" + danger callout.
* **Intake dialog**: source shown read-only when only one is active (dropdown otherwise); *External lot reference* with help text; *Reports to include (optional)* as a three-option radio stack (All / Select by report ID with searchable multi-select + paste / Select by criteria marked *Planned*); live preview "n of m available reports will be included · unknown · duplicates" (⚙ `GET /sources/{id}/reports?ids=` or a dry-run flag on `POST /lots`); intake note; *Technical details* expander showing the pipeline profile (hidden as a control when only one is active) and mapping; CREATE LOT → toast with progress and route to the Canonical workspace when ready (the current `submitIntake` behaviour).

### 5.4 Dataset workspace (`03-workspace.html`)

* Route `/datasets/:id/v:ver/:tab`; `openDataset()` becomes the route handler and loads dataset, reports (paged ⚙), runs for this dataset (⚙ `GET /runs?dataset_id=&dataset_version=` — the current `state.workspaceRuns` session memory goes away) and, for risk_ready, risk-result sets.
* Breadcrumb; banner cells: Lot (ref + chip), Dataset (zone + version + status + chip), Parent snapshot (chip), Created (by/at, gate run), Reports (count + rejected). Stage stepper under the banner, built from the profile route.
* Tabs: Overview · Data · Run functions · Results (badge = active runs) · **publication tab named by transition** (`Evaluate DQ gate` for canonical→dq_passed, `Enrich & publish` for →enriched, `Publish risk-ready` for →risk_ready; absent on risk_ready) · **More ▾** (View lineage, Technical details, All runs in Run history, Open in Advanced operations). The Governance tab is thus demoted to the overflow menu in standard mode.
* Overview: metrics; `.next-action` with a prerequisite checklist; two context panels.
* Data: server-side paging and filters ⚙; expandable report rows loading entities/metrics on demand; a "Show fields" selector to distinguish source (Landing), canonical and enrichment fields; Export only for roles that may export.
* Run functions: groups *Recommended* / *Advanced* (frontend mapping by stage: for dq_passed/enriched, stage 03 recommended, stage 04 optional; for canonical, 01–02 recommended, 03–04 optional; for risk_ready, 05–06 recommended, 07 under "use Case workbench"), purpose lock, collapsed parameters with presets and reset, per-card help and Reference link, pre-queue summary, optional report scope ("Limit to selected reports…" uses the existing `report_ids` field of `POST /dataset-runs`).
* Results: `.run-card` list from the server; status, functions, timings, submitter; "No findings" as a clean result; raw JSON in `.tech-details`; actions (Use in publish tab, View lineage, Cancel for queued ⚙ if an endpoint exists).
* Publication tab: *Evaluate DQ gate* = pick an eligible completed DQ run from a radio list (never paste an ID), blocking severities as explained checkboxes, EVALUATE → preview (eligible/rejected/warnings kept) + dispositions table, PUBLISH → confirmation dialog. *Enrich & publish* = reviewable facts grid (add/edit/remove before submit; `enrichment_values` already accepts a list), publication reason, PUBLISH UNCHANGED vs ADD n FACTS & PUBLISH, both via confirmation dialog with counts and lineage effect. *Publish risk-ready* = reason + confirmation.
* Lineage tab (from More): vertical timeline from `GET /datasets/…/lineage`, link to Oversight. Technical details tab: the raw identifiers and bindings.

### 5.5 Run history (`04-runs.html`)

* Scope (My runs / All permitted / User ⚙), period, group (All/Active/Completed/Failed/Archived), purpose, function, input stage; More: lot/ref, dataset ID, report/entity ID, findings present, max severity, initiated by. Chips + URL + server paging and sorting ⚙ (`GET /runs` currently takes no filters).
* Table columns: status, run chip, purpose · functions, lot · input snapshot, submitted (sort), duration (sort), findings (count + highest severity). Inspect = click the row → `tr.row-detail` directly below with: header + contextual actions (Retry, Open dataset, Evaluate DQ gate, Open evidence set, Review candidates, View lineage), error callout for failures, `.child-grid` of function runs with readable key/values, findings list (`.finding`), raw JSON in `.tech-details`. `inspectRun()` renders into the row instead of `#runInspector`.
* `/runs/:runId` opens with that row expanded (deep link from Home and toasts).

### 5.6 Case workbench (`05-cases.html`)

* Master list (left): one `.work-item` per risk-ready dataset with risk runs or case objects, with a 6-segment progress bar, status line, owner; filter "With risk runs or case work / All / Needing my decision". Glossary panel (risk evidence set, selection batch, final case set, audit handoff case) — this is what lets a user explain the four objects from on-screen text.
* Detail (right): banner (pipeline, reports, evidence set status, batch status) + clickable 6-step stepper; one panel per step:
  1. *Dataset* — filterable table of risk-ready datasets (completed risk runs count), scoped by role.
  2. *Risk runs* — completed runs as `.run-card` with checkboxes (running/failed shown disabled with the reason); "Create risk evidence set (draft)" with *Risk evidence set name*, help text and the count of selected runs; existing sets listed.
  3. *Evidence set* — card with status Draft/Approved, included runs, rationale, approver; APPROVE opens the `approveDialog` (summary + rationale) — replaces `window.prompt` in `approveRiskSet()`; GENERATE CANDIDATES FROM THIS SET → step 4.
  4. *Candidates* — contextual action: thresholds (`min_score`, `max_candidates`) + pre-queue summary; the approved `risk_result_set_id` is injected into `POST /dataset-runs` parameters for `generate_case_candidates`. Shows the resulting batch.
  5. *Review* — `.batch-header` (batch chip, evidence set · generation run, thresholds, decision counts); filters (decision segmented with counts, score ≥, function, reason code, jurisdiction, entity/report); `.candidate` rows with a left colour bar by decision, `.evidence-summary` (reason, source, context) and raw results in `.tech-details`; pending rows carry the decision select + rationale + SAVE; decided rows collapse to one line with "Change decision (requires rationale)"; bulk decision via `bulkDialog` (ticked rows, one rationale, recorded per candidate); FINALISE disabled with the reason while decisions are pending.
  6. *Finalise* — readiness checklist (all decided / ≥1 selected / batch open / role), explanation of what is created, FINALISE → `finalizeDialog` (summary, name, rationale) — replaces the two `window.prompt`s in `finalizeBatch()`; after finalisation the step shows the final case set and the audit handoff cases with REPORT and LINEAGE links.
* API: all of this works with existing endpoints except scoping and candidate filtering/paging ⚙ (`GET /selection-batches/{id}/candidates` returns everything) and bulk decisions (loop over `PUT /selection-candidates/{id}/decision` is acceptable initially).

### 5.7 Reports (`06-reports.html`)

* Library panel (collapsible): find, finalised period, finalised by, selected-case count; table of case sets (name + chip, lot · dataset, period, cases, finalised at/by, OPEN REPORTS). ⚙ `GET /case-sets` needs filters/paging for large libraries.
* Viewer: `.report-heading` with name, status, counts, chips for case set / dataset / evidence set; CASE WORKBENCH back-link; EXPORT menu (selected cases CSV/JSON, lineage CSV, print/PDF view) using the existing CSV endpoints and `window.print()`; "Generated <timestamp> · filters" line that is also written into exports.
* Two tabs: **Selected cases report** (metrics; find/reason/handoff filters; accordion rows → risk basis, source run/function, evidence set, decision, handoff, technical details) and **Processing and lineage report** (ancestry rail — existing `.lineage-rail` — then a vertical timeline per stage/promotion/evidence/batch/final set with the run/function/parameter tables inside collapsed bodies; parameters readable with JSON in `.tech-details`).
* `renderSelectedCasesReport()` / `renderCaseLineageReport()` keep their data mapping; only the layout changes.

### 5.8 Oversight (`07-oversight.html`; replaces Lineage & audit)

* Tab *Data and case lineage*: lookup (type selector + identifier + TRACE) — independent of other pages; banner for the resolved object; clickable 7-stage stepper that expands the matching timeline item; timeline from source XML → lot → snapshots → gate → risk → evidence/candidates → decision/handoff, bodies collapsed, raw JSON in `.tech-details`. Uses `GET /audit-cases/{id}/lineage`, `GET /datasets/…/lineage`, `GET /case-sets/{id}/reports/lineage`; ⚙ lookups by run/report/entity need a resolver.
* Tab *Access and action audit*: filters (period, actor, role, action, outcome Allowed/Denied with `i` text, target type, target reference), EXPORT CSV, legend explaining Allowed/Denied in words; table (outcome, time, actor · role, action, target with chip, stage/purpose, request ID); server paging ⚙ (`GET /audit` only takes `limit`). Read-only.

### 5.9 Settings (`08-settings.html`; replaces Administration)

* Sub-navigation: Users and access · Data sources · Pipeline profiles · Functions and mappings · System status · (Developer) Advanced operations, API documentation.
* Users: table with accordion rows (effective permissions checklist, assignment history ⚙), CREATE USER dialog (`POST /users`), EDIT ROLES dialog (`PUT /users/{id}/roles`), DEACTIVATE ⚙, and a warning callout when `acceptance-*` users are present (test-data leakage) with a one-click deactivate.
* Data sources: endpoint reference editable in a dialog with TEST CONNECTION ⚙ and a secret *reference* only (never the secret); enable/disable ⚙; last successful access ⚙. Replaces `window.prompt` in `editSource()`.
* Pipeline profiles: route + bindings, VALIDATE, NEW VERSION (versioned, not overwritten ⚙ — `PUT /pipeline-profiles/{id}` currently overwrites).
* Functions and mappings: table with lifecycle (active/draft/retired), SCHEMA, NEW VERSION, ACTIVATE, RETIRE (existing endpoints), link to the read-only reference.
* System status: the former health panel plus migrations, queue age, failed runs.

### 5.10 Function reference (`09-function-reference.html`; replaces Function catalogue in nav)

* Read-only; search + stage/purpose/zone/parameters filters; one collapsible `.run-card` per function with purpose, inputs, parameters (name, type, default, meaning), output codes, typical use, applicable zones. Anchors `#function_code` so function cards can link to them. "Manage configuration" link for admins.

---

## 6. What leaves the standard interface, and where it goes

| Current element | Decision | Where it lives now | Why |
|---|---|---|---|
| "Acting as" user selector | **Remove** from standard UI | `/advanced` behind a dev flag | Impersonation is not role selection; test users leaked into it; unsafe for production (brief §4) |
| Health panel on the landing page | **Demote** | Masthead status dot → panel; Settings › System status | Technical health was the first thing analysts saw |
| Work queue counters (DQ work, Publication work, Risk ready) | **Replace** | Home attention cards (actionable, scoped, linked) | Counters had no action and wrong labels |
| "Runs requiring attention" list | **Replace** | Home › Recent activity (filtered, paged, honest heading) | It showed the first six runs of any status |
| Dataset workspace nav entry + empty page | **Remove** | Contextual route `/datasets/…` | Empty destination in primary navigation |
| Governance tab in the workspace | **Demote** | More ▾ › View lineage (standard); tab stays in Advanced | Rarely needed by analysts, duplicated by Oversight |
| Pipeline profile dropdown in Intake | **Hide when single** | Technical details expander | No meaningful choice; jargon |
| "Report subset" text box | **Replace** | Reports to include (All / by ID / by criteria) with preview | Mode was unclear; no validation |
| Run ID paste box in DQ gate | **Replace** | Radio list of eligible completed runs | Users should never transcribe UUIDs |
| Single-fact enrichment form | **Replace** | Reviewable facts grid; "Publish unchanged" explicit | Multiple facts; clearer optional/required distinction |
| Run inspector at page bottom | **Replace** | Accordion row under the inspected run | Relationship to the row was unclear |
| Four stacked panels on Case workbench | **Replace** | Master–detail + 6 steps | Objects shown without their stage relationship |
| "Create Draft Set" / "Set name" | **Rename** | "Create risk evidence set (draft)" / "Risk evidence set name" with `i` | Terminology |
| `window.prompt` (approve, finalise ×2, edit source) | **Replace** | Native dialogs with summaries and rationale fields | Validation, explanation, cancel |
| Report page with two continuous sheets | **Replace** | Library + viewer with two tabs + Export menu | Discoverability; separation of preview/export/print |
| Lineage & audit page depending on prior navigation | **Replace** | Oversight with its own lookup; two tabs | No hidden cross-page state |
| Function catalogue nav entry | **Move** | Utilities › Function reference; Settings › Functions for admins | Reference, not a workflow step |
| Administration nav entry | **Move** | Settings (profile menu / Utilities, admin only) | Configuration, not workflow |
| API CONTROL PLANE masthead link | **Move** | Profile menu / Settings › Developer | Developer tool |
| POLISHED UI ↗ link | **Replace** | Theme stays a `?ui=polished` query parameter / user preference; not a masthead link | Not a user task |
| The whole current nine-page UI | **Keep** | `/advanced`, same APIs and permissions, defects fixed | Developers, support, demos, unusual investigations |

---

## 7. API / data work the UI depends on

Ordered by how much UI it unblocks. Items marked *interim* have a frontend-only fallback that is acceptable for a first release.

| # | Need | Endpoint(s) | Unblocks | Interim |
|---|---|---|---|---|
| A1 | Authenticated identity + effective roles | `GET /me` (or identity-provider header → user) | Shell nav, role scoping, removal of `x-cbcr-user` impersonation in production | Derive from `GET /users` for the header user |
| A2 | Server-side "own records" scoping and filters/pagination for lots, datasets, runs | `GET /lots|datasets|runs?scope=me|all|user:<id>&…&page=&page_size=&sort=` using `lot.received_by`, `dataset.created_by`, run creator | Lifecycle, Run history, Home scopes | Client-side filtering of what the API returns (not a security control) |
| A3 | Runs for one dataset version | `GET /runs?dataset_id=&dataset_version=` | Workspace › Results after refresh | Filter `GET /runs` client-side: its summaries already carry `dataset_id`, `dataset_version`, `requested_by`, `selected_functions`, `input_zone` (see `RunService.list` in `runs.py`), which also gives an interim "My runs" scope. Note `list_runs` in `api.py` re-fetches every run to check visibility (N+1); fold the permission check into the query when adding filters |
| A4 | Dashboard aggregates | `GET /dashboard?period=&scope=` → card counts, lots-by-zone, runs-by-status, median stage durations, DQ eligible/rejected | Home | Compute from list endpoints |
| A5 | Audit filters and paging | `GET /audit?from=&to=&actor=&role=&action=&outcome=&target_type=&target_ref=&page=` | Oversight › audit | `limit=` only |
| A6 | Lookup by any ID / reference | `GET /lookup?id=` → `{type, route}` | Global find, Oversight lookup, deep links | Try each list endpoint in parallel |
| A7 | Intake preview / validation | `GET /sources/{id}/reports?ids=` or `POST /lots?dry_run=1` | Intake dialog preview counts, unknown/duplicate IDs | Submit and surface errors |
| A8 | Candidate filtering/paging; bulk decision | `GET /selection-batches/{id}/candidates?decision=&min_score=&…`, `POST /selection-batches/{id}/decisions` | Case workbench › Review at scale | Client filtering; loop single decisions |
| A9 | User deactivation, assignment history | `PUT /users/{id}` (active flag), `GET /users/{id}/history` | Settings › Users | Hide buttons |
| A10 | Source test-connection, enable/disable, last access | `POST /sources/{id}/test`, `PUT /sources/{id}` (enabled) | Settings › Sources | Hide buttons |
| A11 | Versioned pipeline profiles | `POST /pipeline-profiles/{id}/versions` instead of overwrite | Settings › Profiles | Keep PUT with a confirmation |
| A12 | Distinguish 403 from empty | API already returns 403; the *frontend* must stop mapping it to `[]` (`safeTask(..., [])`) | Honest empty states everywhere | Frontend-only |
| A13 | Test isolation | Acceptance tests use a separate database and clean up `acceptance-*` users | Settings warning disappears | Deactivate manually |

The frontend must never simulate row-level security by hiding rows the API returned; scope controls are a convenience until A2 lands.

---

## 8. Implementation approach for `web/`

### 8.1 Files

```
web/
  index.html            standard UI shell (masthead/sidebar placeholders + <main id="view">)
  advanced.html         the current index.html, served at /advanced (unchanged markup, defects fixed)
  niche.css             unchanged except the defect fix in §9.1
  wip-workbench.css     unchanged
  reports.css           unchanged
  redesign.css          from mockups/redesign.css (drop section 16 "mock-only" and section 18 once niche.css is fixed)
  app/
    api.js              api(url, options) → throws ForbiddenError / ApiError; never swallows 403
    router.js           path → page module; parses/serialises query state; History API
    components.js       idChip, stepper, lotStage, filterBar, accordion helpers, confirmDialog, techDetails, emptyState, toast
    shell.js            renderShell(me) → masthead + nav from roles (port of mock.js Part A, minus personas)
    pages/home.js, lifecycle.js, workspace.js, runs.js, cases.js, reports.js, oversight.js, settings.js, reference.js
  niche.js              retained for advanced.html only
```

### 8.2 Conventions (keep what already works)

* Rendering stays string templates + `esc()`; events use **delegation on `document`** exactly as `mock.js` Part B does (one listener for chips, toggles, tabs, menus, dialogs, segmented controls). This removes the many `$$('[data-…]').forEach(button => button.onclick = …)` re-binding passes in `niche.js`.
* Page modules export `render(root, route)` and `destroy()`; they fetch their own data with the filters from the route; they never read other pages' state. The only global is `me` (identity + roles).
* Long-running actions: after `POST /dataset-runs` or `/lots`, show the toast, navigate to the durable route (`/runs/:id` or the workspace), and poll there; leaving the page does not lose the run.
* Every mutation goes through a confirmation dialog built by `confirmDialog({title, summary: [[label, value]…], fields, confirmLabel})` that returns a promise.
* Empty states call `emptyState({why, action})`; a 403 renders "You don't have permission to view X" rather than "No X".
* Keep `title()`, `short()`, `formatDate()`, `status()` helpers; `short()` is only used inside `idChip()`.

### 8.3 Sequence

1. Fix the `niche.css` parse defect (§9.1) and ship `advanced.html` = current UI. Zero visual change for existing users.
2. `api.js` (403 handling), `router.js`, `shell.js` with roles from A1/interim; `components.js` with ID chip, accordion, dialogs, tech-details, stepper.
3. Run history (smallest page, exercises filter bar + accordion), then Home.
4. Data lifecycle + intake dialog; Dataset workspace with routed tabs and server-loaded results.
5. Case workbench; Reports; Oversight.
6. Settings; Function reference; remove impersonation from the standard shell.
7. Responsive/accessibility pass; role-based acceptance tests; keep `/advanced`.

---

## 9. Defects found in the current UI while building the mockups

1. **`niche.css` is truncated by a parse error.** `dialog{…width:min(550px,calc(100% - 28px);…}` is missing a `)`. Browsers consume the rest of the file looking for the closing parenthesis, so **everything after that rule is dropped**: `dialog::backdrop`, `dialog form`, `.dialog-head`, `.icon-button`, `.dialog-actions`, `#toast` (so toasts never animate/show correctly in the polished theme — the div sits visible at the bottom of the page), `[hidden]{display:none!important}` (so any element with a `display` rule ignores `hidden`), and **all three `@media` blocks** (no responsive behaviour). One-character fix. `redesign.css` §18 restores these rules for the mockups only.
2. `safeTask(api(...), [])` turns 403 into an empty list (brief §8.5) — e.g. the Admin page shows "User/role listing requires access-management permission" as if it were data.
3. `renderWork()` heading "Runs requiring attention" over `state.runs.slice(0, 6)` (brief §7.2).
4. `window.prompt` used in `approveRiskSet`, `finalizeBatch` (twice) and `editSource`.
5. `state.workspaceRuns` is session-only; `renderResults()` forgets runs on refresh.
6. `applicableFunctions()` hard-codes stage→zone mapping in the client (`{canonical:[01..04], dq_passed:[03,04], …}`); it should come from the function catalogue (`GET /functions` could return `applicable_zones`) so a configuration change does not need a UI change.
7. Toast after approval tells the user to "Copy its ID into Generate Case Candidates" — the manual bridge the redesign removes.
8. `index.html` mixes WIP-only links (`.wip-only`) and theme switching via query string; the standard shell should carry neither.

---

## 10. Acceptance criteria (extends brief §12)

* The standard sidebar shows at most 5 workflow entries plus Oversight (role-dependent); Function reference, Settings, Advanced operations and API docs appear only under Utilities / the profile menu.
* No `window.prompt`/`confirm` remains in the standard UI; every mutation shows a summary dialog with counts and lineage effect.
* Every identifier is rendered by `idChip()`; clicking expands it, COPY copies the full value.
* Refreshing any of the routes in §3.3 restores the same view, including the expanded run, the workspace tab and the case-workbench step.
* Workspace › Results lists runs created in previous sessions and by other permitted users.
* "No findings" renders as a clean-result callout.
* Opening Oversight with no prior navigation lets the user trace any ID; "Denied" is explained inline and never styled like a case decision.
* An Analyst never sees Oversight or Settings; an Auditor never sees mutation buttons; a 403 renders as a permission message, not an empty list.
* Candidate generation can be started from an approved evidence set without the user seeing or copying its ID.
* The Reports page opens on a library; a case set's reports are two tabs with a working Export menu and print view.
* `/advanced` renders the previous nine-page UI with the §9 defects fixed and the same permission model.
* Under 780 px every page is usable without horizontal page scroll (tables and steppers scroll internally).
