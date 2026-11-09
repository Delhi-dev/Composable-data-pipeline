# CbCR Control Plane - Updated demonstration and scenario walkthrough

**Updated:** 9 November 2026  
**UI:** Standard workflow interface at `http://127.0.0.1:8011/`  
**API documentation:** `http://127.0.0.1:8011/docs`  
**Advanced interface:** `http://127.0.0.1:8011/advanced`

## 1. Purpose

This guide demonstrates the complete implemented journey:

`PostgreSQL source -> intake lot -> canonical dataset -> DQ run -> DQ gate -> DQ-passed -> enrichment -> risk-ready -> risk analysis -> approved evidence set -> candidate generation -> human decisions -> final case set -> reports -> lineage and access audit`

It also covers administration, the function catalogue, filtering, run inspection, exports, error handling, and advanced/API-only capabilities.

The steps use an example external lot reference such as `DEMO-2026-11-01`. Use a new reference for each demonstration. IDs and result counts are generated at runtime and will differ from the examples.

## 2. Before starting

### 2.1 Start the application

From the repository root:

```powershell
.\Start_Local_PostgreSQL.ps1 -WebPort 8011
```

Open `http://127.0.0.1:8011/`. The masthead should show **System OK**. Open it to confirm that the persistence backend is PostgreSQL and that the database is connected.

### 2.2 Confirm source data

The registered PostgreSQL source must expose at least one CbCR report through the configured canonical API view. If no reports are exposed, intake cannot create a useful dataset.

Useful verification points:

- **Settings > Connected sources** shows the intended PostgreSQL source.
- Swagger `GET /api/v1/sources` returns that source.
- The source endpoint should point to the PostgreSQL host used by the application, not `localhost` when the application is deployed in another container or host.

### 2.3 Personas and development identity switching

In the local launcher, `CBCR_UI_IMPERSONATION=1` enables **Viewing as** in the profile menu. This is for demonstrations and testing only.

| Persona | Typical roles | Main responsibility |
|---|---|---|
| Administrator | `platform_admin` | Users, roles, sources, configuration and oversight |
| DQ/Risk analyst | `dq_analyst`, `risk_analyst` | Intake, quality checks, publication and risk analysis |
| Case reviewer | `case_manager` | Evidence approval, candidate decisions and finalization |
| Auditor | `auditor` | Read-only lineage and access/action audit |

Use the profile menu's **Viewing as** selector to change persona. If the selector is absent, identity switching is disabled; use the user supplied by the deployment's authentication layer.

### 2.4 Important data-dependent outcomes

- A successful run may legitimately have zero findings.
- Candidate generation produces candidates only from risk results in the approved evidence set and after its threshold filters are applied.
- To make a broad demonstration set, leave **Allowed severities** and **Allowed rules** blank and use a low minimum risk score such as `0`.
- The domestic-context functions require suitable domestic demo/source records for the CbCR entities. Their output depends on the available linkage and domestic facts.

---

## S0 - Administrator setup and orientation

**Persona:** Administrator  
**Pages:** Home, Settings, Function reference

1. Open **Home**.
   - Review the attention cards: failed runs, active runs, DQ work, publication work and pending case decisions.
   - Review the bounded recent activity list and stage/run summaries.
   - Card counts represent pending workflow work, not merely all historical datasets in a zone.

2. Open **System OK** in the masthead.
   - Confirm backend, database, API version and worker status.
   - Click outside or press `Esc` to close it.

3. Use the global **Find by ID or reference** box.
   - It accepts complete lot, dataset, run, risk evidence set, selection batch, case set and audit-case IDs, plus external lot references.
   - It routes directly to the appropriate context.

4. Open **Settings > Users and roles**.
   - Click **Create user**.
   - Enter a user ID and display name.
   - Assign one or more roles, then save.
   - Edit the user to change roles or active status.
   - The current administrator cannot deactivate their own account.

5. Open **Settings > Connected sources**.
   - Inspect the PostgreSQL source definition.
   - The endpoint may contain the canonical view query parameter.
   - Passwords should not appear in the endpoint; use an environment-backed secret reference.
   - Registering or editing a source changes its connection definition but does not copy source data into the control-plane database.

6. Open the remaining Settings tabs.
   - **Pipeline profiles:** view the configured stage routes.
   - **Functions and mappings:** view active function handlers, stages, purposes and parameter definitions.
   - **System status:** view the backend's detailed health response.

7. Open **Function reference**.
   - Search by function name, code, stage or purpose.
   - Expand a function to see its plain-language purpose, parameters and technical definition.
   - Retired functions are hidden by default; use **Show retired** only when needed.

**Expected result:** administrative configuration is visible, role descriptions are meaningful, and ordinary workflow users do not see Settings unless authorized.

---

## S1 - Create an intake lot and inspect the canonical dataset

**Persona:** DQ/Risk analyst  
**Page:** Data lifecycle

1. Open **Data lifecycle**.
   - Each card represents one intake lot.
   - Its five-stage strip shows the immutable snapshots already created.
   - Filters include search, contained stage and date range. Users with broad access also see owner and scope filters.

2. Click **Create intake lot**.

3. Complete the dialog:
   - **Source:** select the registered PostgreSQL CbCR source.
   - **External lot reference:** enter a unique value such as `DEMO-2026-11-01`.
   - **Report scope:** choose either:
     - **All reports exposed by the source**, or
     - **Only the report IDs below** and paste comma-separated or one-per-line IDs.
   - Duplicate IDs are removed and the dialog shows the unique count.
   - **Notes:** enter optional demonstration context.

4. Click **Create lot**.

5. The application opens the new **Canonical** dataset workspace.
   - The lot creates immutable Landing and Canonical snapshots.
   - The workspace banner shows the external lot reference, dataset ID/version, zone, report count, status and parent snapshot.
   - Click an abbreviated identifier to expand it; use the separate copy control to copy it.

6. Open the workspace tabs:
   - **Overview:** counts, stage rail and recommended next action.
   - **Data:** report ID, reporting entity, reporting-period end, entity count and jurisdiction count. Click **Inspect** to view constituent entities, jurisdiction metrics and technical payload.
   - **Run functions:** functions eligible for the current zone.
   - **Results:** runs already executed on this exact dataset version.
   - **Publish / enrich:** the permitted transition to the next zone.
   - **Lineage:** parents and publication events.

7. Return to **Data lifecycle** and search for the external lot reference.
   - One lot card should show Landing and Canonical as complete.
   - **Run DQ / gate** opens the canonical workspace.

**Expected result:** a new lot exists with Landing and Canonical snapshots; source data is visible as normalized report/entity/metric structures without overwriting the source XML records.

---

## S2 - Run data-quality functions

**Persona:** DQ/Risk analyst  
**Starting point:** Canonical workspace

1. Open **Run functions**.

2. Select a representative DQ run, for example:
   - **Validate receipt identity** - confirms required report identity fields.
   - **Detect duplicate report** - looks for duplicate report identity/content indicators.
   - **Check completeness** - verifies configured metrics such as `revenue`, `profit_before_tax` and `employees`.
   - **Check related revenue share** - compares related-party revenue share with the configured threshold, for example `0.5`.

3. Expand **Show parameters** only where configuration is required.
   - Boolean parameters render as checkboxes.
   - Lists render as comma-separated values with guidance.
   - Numeric fields use numeric inputs.
   - Selected function cards are visually highlighted.

4. Click **Review and queue run**.

5. Review the confirmation dialog:
   - dataset and version;
   - input zone;
   - selected functions;
   - resolved parameters.

6. Click **Queue run**.
   - The application opens **Run history** with the new run expanded.
   - Status normally moves through `queued`, `running`, then `completed` or `completed_with_errors`.

7. Inspect the completed run inline.
   - Each child function shows status, resolved parameters, summary and artifacts.
   - Findings show severity, message, report/entity identifiers and evidence.
   - An empty findings list means the function completed without detecting its configured exception; it does not mean the run failed.

8. Use Run history filters:
   - status, purpose, function, zone, owner, date range and search;
   - status supports combined values such as queued and running;
   - expand and copy any full run ID from its identifier chip.

9. Return to the dataset's **Results** tab.
   - Click **Inspect** to expand run details below that row without leaving the workspace.

**Expected result:** the DQ run is stored with independently executed function results, parameters, findings and timestamps. The canonical dataset remains immutable.

---

## S3 - Evaluate the DQ gate and publish DQ-passed

**Persona:** DQ/Risk analyst  
**Starting point:** Canonical workspace > Publish / enrich

1. Open **Publish / enrich**. The panel is titled **Evaluate DQ gate**.

2. Select the completed DQ run from S2.
   - Labels show a readable short run ID, completion context, function count and finding count.

3. Choose blocking severity:
   - **Errors only** allows warnings to continue; or
   - **Warnings and errors** rejects reports with either severity.

4. Click **Evaluate gate**.

5. Review the preview:
   - eligible report count;
   - rejected report count;
   - per-report disposition;
   - reason codes or confirmation that there are no blocking findings.

6. Enter a publication reason, such as `DQ gate reviewed; error-level findings block publication`.

7. Click **Publish DQ-passed**, review the transition confirmation and confirm publication.

8. The application opens the new DQ-passed dataset.
   - Only the gate-eligible lot is represented according to the evaluation dispositions.
   - The original Canonical snapshot is retained.

9. Open **Lineage**.
   - Confirm Landing, Canonical and DQ-passed ancestry.
   - Confirm the publication event includes its reason and evaluation/gate context.

**Expected result:** a separate DQ-passed snapshot is created with traceable gate evidence; nothing is updated in place.

---

## S4 - Optional pre-enrichment, governed enrichment and risk-ready publication

**Persona:** DQ/Risk analyst

### A. Optional pre-enrichment functions

1. In the DQ-passed workspace, open **Run functions**.
2. Run applicable functions such as **Resolve entity** or **Enrich jurisdiction reference**.
3. Inspect the results. Zero findings can be expected when all source values already satisfy the configured rule.

### B. Publish the Enriched snapshot

1. Open **Publish / enrich**. The panel is titled **Enrich and publish**.
2. Choose one of two paths:
   - **Publish unchanged:** use when no enrichment fact is required; or
   - click **Add fact** one or more times and provide:
     - report ID;
     - optional entity scope;
     - attribute name;
     - value;
     - source reference;
     - optional confidence from `0` to `1`.
3. Enter a publication reason.
4. Click **Publish unchanged** or **Publish with facts**.
5. Review and confirm the publication summary.

The enrichment rows are governed facts attached to the downstream snapshot. They do not silently overwrite the original source XML.

### C. Publish Risk-ready

1. In the Enriched workspace, review Data and Results.
2. Open **Publish / enrich**.
3. Enter a reason such as `Enrichment reviewed; ready for risk analysis`.
4. Click **Review and publish Risk ready**, then confirm.

**Expected result:** the lot timeline now contains Landing, Canonical, DQ-passed, Enriched and Risk-ready snapshots, each with its own immutable dataset ID and parent link.

---

## S5 - Run risk analysis, including domestic-context analysis

**Persona:** Risk analyst  
**Starting point:** Risk-ready workspace > Run functions

### A. Direct CbCR risk analysis

1. Select representative functions, for example:
   - **Effective tax rate outlier**;
   - **Profit/presence mismatch**;
   - **Cross-match domestic turnover**;
   - **Score risk components**.
2. Configure thresholds appropriate to the demo data. Example starting values:
   - minimum ETR: `0.05`;
   - minimum profit margin: `0.25`;
   - maximum employees: `2`.
3. Review and queue the run.
4. Inspect findings and evidence in Run history or the workspace Results tab.

### B. Two-source domestic-context chain

1. First run **Profit/presence mismatch** on the Risk-ready dataset.
2. Start a second run and select **Load domestic context for screened reports**.
   - The `screening_run_id` parameter is a selector populated from eligible completed screening runs on this dataset.
   - Select the run from the previous step and provide the fiscal year if required.
3. After it completes, select **Outbound payments to low-substance jurisdictions** and/or **Interest stripping**.
   - The `domestic_context_id` parameter is populated from completed domestic-context loader artifacts.
   - Select the intended context rather than copying a UUID manually.
4. Queue and inspect the combined-source analysis.

The domestic data is accessed through its adapter and linked by configured identifiers/link confidence. The framework does not merge the two source databases into one operational database.

### C. Verify risk runs

1. Open **Run history**.
2. Filter **Purpose = risk_assessment** and optionally select a function.
3. Record which completed runs should become governed evidence for candidate generation.

**Expected result:** completed risk runs contain findings/risk results with function code, parameters and evidence. Runs remain separate until a reviewer deliberately groups selected runs into an evidence set.

---

## S6 - Approve evidence, generate candidates and record human decisions

**Persona:** Case reviewer  
**Page:** Case workbench

1. Open **Case workbench**.
   - Filter by external lot reference, dataset ID, owner or progress.
   - Each Risk-ready row shows its progress through evidence approval, candidate review and finalization.

2. Click **Start / resume** for the required Risk-ready dataset.

3. **Step 1 - Confirm dataset**
   - Confirm dataset/version, report count and completed risk-run count.
   - Click **Choose evidence**.

4. **Step 2 - Evidence set**
   - Review completed risk runs for this exact dataset version.
   - Click **Create draft set**.
   - Enter a meaningful name such as `DEMO-2026-11 approved risk evidence`.
   - Select the exact completed runs whose results should be frozen as evidence.
   - Create the draft.
   - Click **Approve evidence set**, enter a rationale and approve it.

5. **Step 3 - Generate candidates**
   - The approved `risk_result_set_id` is injected automatically.
   - For the broadest demonstration, set **Minimum risk score** to `0` and leave **Allowed severities** and **Allowed rules** blank.
   - Click **Queue candidate generation**.
   - The asynchronous `generate_case_candidates` run creates a new selection batch; it does not alter older batches or decisions.

6. Return to Case workbench and resume the dataset.
   - Open the newly created selection batch.

7. **Step 4 - Review candidate evidence**
   - Review batch status, source evidence set, counts and shown candidates.
   - Filter by text, decision state or minimum score.
   - Expand evidence for a candidate.
   - Enter a rationale and choose **Select**, **Do not select** or **Defer**.
   - Saved cards show rationale, deciding user and decision time.
   - Decide every candidate before finalization; at least one must be selected.

8. **Step 5 - Finalize selected cases**
   - Review the readiness checklist:
     - no pending decisions;
     - at least one selected candidate;
     - selection batch remains open.
   - Enter the final case-set name and rationale.
   - Click **Finalize and create audit handoff**.

9. Reopen the finalized batch.
   - It is read-only.
   - The page links to its final reports.

**Expected result:** an immutable final case set and audit-handoff records are created from the selected decisions. The selection batch retains candidate evidence and human rationales.

---

## S7 - View and export final reports

**Persona:** Case reviewer, administrator or authorized auditor  
**Page:** Reports

1. Open **Reports**.
   - The library contains finalized case sets only.
   - Filter by name, external lot reference, dataset ID, case-set ID, date range or finalizing user.

2. Open **Cases** for the final case set.
   - Review selected report/entity, audit-case ID, risk score/reason, decision rationale, decider and audit-handoff status.
   - Expand evidence for source risk results.
   - Use **Download CSV** for the final selected-case register.
   - Use **Download PDF report** for a purpose-built report containing the case-set summary, selected-case register, human decisions, audit handoff, source-document references and risk evidence. It is not a printout of the HTML page.

3. Open **Traceability**.
   - Review dataset ancestry and all publication transitions.
   - Review run IDs, functions, resolved parameters, summaries and the approved evidence set.
   - Use **Download PDF report** for the formatted lineage appendix, or **Download CSV** for the lineage/execution register.

4. Copy the report URL and open it in a new tab.
   - The route is stable and opens the same case set and selected report tab.

**Expected result:** the final selected cases and their complete execution/data lineage are available as readable UI reports, printable pages and CSV files.

---

## S8 - Auditor lineage and access/action review

**Persona:** Auditor or Administrator  
**Page:** Oversight

### A. Trace an object

1. Open **Oversight > Trace an object**.
2. Enter a complete identifier or external lot reference.
3. For an audit-case ID, review the structured end-to-end timeline:
   - source document/intake lot;
   - dataset ancestry;
   - DQ and promotion evidence;
   - risk runs and approved evidence;
   - selection batch and decision history;
   - final case set and audit-handoff events.
4. Try an external lot reference, dataset ID, run ID and case-set ID.
   - **Open context** routes to the filtered lifecycle/workspace/run/report page.

### B. Access and action audit

1. Open **Oversight > Access and action audit**.
2. Filter by actor, role, action, outcome, target or date range.
3. Expand event details as required.

Interpretation:

- `allowed` means the role policy permitted the attempted application action.
- `denied` means access control blocked it.
- These values do **not** mean that a taxpayer/case was selected or rejected for human audit.

Use Previous/Next to page through audit events.

**Expected result:** an authorized oversight user can trace a final case to the source and review controlled application activity without changing workflow data.

---

## S9 - Recovery, empty-state and control demonstrations

These are useful acceptance checks after the primary demo.

1. **No function selected:** submit Run functions without selecting anything. The UI asks for at least one function and queues nothing.
2. **Unknown report subset:** create a By-ID lot with an unknown report. The source adapter rejects it and the dialog remains available for correction.
3. **Empty findings:** open a successful run with `[]` findings. The UI explains that no configured exception was found.
4. **Missing rationale:** try to decide a candidate without rationale. No decision is submitted.
5. **Pending candidates:** open finalization with pending decisions. The readiness checklist disables finalization and explains why.
6. **Finalized batch:** revisit a finalized selection batch. Decision controls are read-only.
7. **No reports yet:** open Reports before any batch is finalized. The empty state directs the user to finalize a batch.
8. **Unknown route:** open `/nothing-here`. The UI shows Page not found and a Return home link.
9. **Deep link:** open a complete run/workspace/report URL directly. The standard UI shell loads and restores that context.
10. **Responsive/keyboard:** narrow the browser, tab through controls, open a dialog and press `Esc`. Navigation remains usable, focus is visible and the dialog closes.

---

## S10 - Advanced and API-only capabilities

These capabilities exist but are intentionally outside the standard daily workflow.

| Capability | Location |
|---|---|
| Choose non-standard pipeline profiles | `/advanced` intake workflow |
| Inspect detailed technical controls | `/advanced` |
| Execute APIs directly | `/docs` |
| Register, activate or retire function versions | Function administration APIs |
| Maintain canonical mappings/data dictionary | Mapping and data-dictionary APIs/administration |
| Change audit-handoff status or external reference | Audit-case status API |
| Inspect raw API payloads | Swagger `/docs` |

The standard UI should be used for the normal governed journey; the advanced interface and Swagger are intended for administrators, developers and controlled troubleshooting.

## 3. Demonstration completion checklist

The walkthrough is complete when all applicable statements are true:

- [ ] A PostgreSQL source is registered and connected.
- [ ] A unique intake lot was created.
- [ ] Landing and Canonical datasets exist.
- [ ] A multi-function DQ run completed and its findings were inspected.
- [ ] DQ gate dispositions were previewed before DQ-passed publication.
- [ ] DQ-passed, Enriched and Risk-ready snapshots were created.
- [ ] At least one risk run completed.
- [ ] The dependent domestic-context chain was demonstrated, where source data permits.
- [ ] A named risk evidence set was created and approved.
- [ ] Candidate generation created a selection batch.
- [ ] Every candidate received a reasoned human decision.
- [ ] A final case set and audit-handoff records were created.
- [ ] Selected-cases and traceability reports were viewed/exported.
- [ ] An audit case was traced end to end.
- [ ] Access/action events were filtered and correctly interpreted.

## 4. Known boundaries of this walkthrough

- Development impersonation is not production authentication. Production requires a trusted identity provider or reverse proxy.
- Intake shows the unique requested-ID count but does not yet perform a source-side dry-run count before submission.
- Lifecycle paging is currently applied after a capped dataset query; large installations require server-provided total/cursor metadata.
- Existing acceptance-test data is hidden by default where practical but is not destructively removed.
- Function lifecycle and deep mapping administration remain advanced/API responsibilities.

## 5. Coverage map

| Area | Scenario |
|---|---|
| Health, identity, global lookup | S0 |
| Users, roles, sources and settings | S0 |
| Function catalogue | S0 |
| Intake and report selection | S1 |
| Lot timeline and dataset workspace | S1 |
| Data quality and asynchronous runs | S2 |
| Gate evaluation and DQ publication | S3 |
| Enrichment and risk-ready publication | S4 |
| Direct and domestic-context risk analysis | S5 |
| Evidence approval and candidate generation | S6 |
| Human decisions and finalization | S6 |
| Selected-case and lineage reports | S7 |
| Audit-case lineage and access audit | S8 |
| Errors, empty states and controls | S9 |
| Advanced interface and APIs | S10 |
