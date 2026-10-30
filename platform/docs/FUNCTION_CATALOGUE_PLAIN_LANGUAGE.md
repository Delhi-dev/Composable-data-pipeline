# CbCR Function Catalogue: Plain-Language Definitions and Parameters

## 1. Purpose and source of truth

This document explains the currently implemented CbCR data-quality, normalisation/enrichment, risk-analysis and case-review functions in functional language. It also records every user-supplied parameter accepted by the PostgreSQL implementation.

The catalogue was checked on 28 October 2026 against:

- the active rows in `cbcr_control.function_definition` in the local PostgreSQL database;
- `platform/cbcr_platform/bootstrap.py` and `platform/cbcr_platform_pg/bootstrap.py`, which register the functions and parameter schemas;
- `platform/cbcr_platform/function_library.py`, which contains the function logic;
- `platform/cbcr_platform_pg/runs.py`, which validates and orchestrates PostgreSQL runs; and
- `platform/cbcr_platform_pg/case_selection.py` and `domestic.py`, which implement governed case generation and domestic-data reduction.

If a future database migration changes the active function catalogue, the live catalogue returned by `GET /api/v1/functions` takes precedence and this document should be updated.

## 2. How functions run

Each function is selected independently and runs asynchronously against a versioned dataset snapshot. Selecting several functions creates one parent dataset run and a separate child run for each selected function. One function's finding is not automatically used by another function unless a dependency is explicitly described below.

The available stages and input zones are:

| Stage | Functional area | Permitted input zone |
|---|---|---|
| 01 | Receipt identity and duplicate checks | `landing` or `canonical` |
| 02 | Normalisation readiness | `canonical` |
| 03 | Entity and reference enrichment readiness | `canonical`, `dq_passed` or `enriched` |
| 04 | Data-quality checks | `canonical`, `dq_passed` or `enriched` |
| 05 | CbCR-only risk screening | `risk_ready` |
| 06 | Risk scoring and domestic-data analysis | `risk_ready` |
| 07 | Case-review preparation | `risk_ready` |

Risk-assessment and case-review functions cannot run on canonical, DQ-passed or enriched data. The dataset must first be published to `risk_ready`.

### 2.1 Common output terms

- **Summary**: counts and parameter values that describe the completed run.
- **Finding**: a report/entity/jurisdiction-level condition raised by a rule. A successful run may validly have zero findings.
- **Artifact**: a structured output such as a normalisation plan, domestic request, score, context or case candidate.
- **Risk result**: the PostgreSQL persistence of a risk finding or risk artifact in `cbcr_risk.result`.
- **Case candidate**: a report/entity combination assembled from an approved Risk Result Set for human review.

### 2.2 Parameter conventions

- Percentage thresholds are decimal ratios: `0.25` means 25%, `0.05` means 5%, and `2.0` means a 2:1 ratio.
- Parameter names must exactly match the catalogue. Unknown parameters are rejected.
- Omitted parameters receive the defaults shown below.
- Empty `allowed_rules` or `allowed_severities` arrays mean “do not restrict by this field.”
- Monetary thresholds use the units stored in the domestic source. These functions do not perform foreign-exchange conversion.
- Internally injected keys such as `__domestic` and `__screened_report_ids` are orchestration values, not user parameters.

## 3. Stage 01 — receipt and identity quality

### 3.1 `validate_receipt_identity`

**Plain-language definition:** Confirms that each report has both a message reference and a reporting-entity identifier. These two values are needed to identify the received report reliably.

**Finding raised:** `RECEIPT_IDENTITY_MISSING` with severity `error` when either value is absent. The evidence says which of the two values is present.

**Parameters:** None.

**Output:** A count of reports checked and zero or more findings.

### 3.2 `detect_duplicate_report`

**Plain-language definition:** Looks for two reports in the dataset with the same business identity: message reference, reporting-entity identifier and reporting-period end date.

**Finding raised:** `DUPLICATE_REPORT` with severity `error` for every later occurrence of the same business key. The evidence identifies the first report treated as the original.

**Parameters:** None.

**Output:** The number of unique business keys and zero or more findings.

## 4. Stage 02 — normalisation readiness

### 4.1 `normalize_currency`

**Plain-language definition:** Checks that every report contains a three-character reporting-currency code and records the desired target currency in a normalisation plan.

**Important current behaviour:** It does **not** obtain exchange rates or convert monetary values. It validates readiness and produces a plan only.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `target_currency` | string | `EUR` | Three-letter target currency to record in the normalisation plan. The value is converted to uppercase. |

**Finding raised:** `INVALID_CURRENCY_CODE` with severity `error` if the source code is missing or is not three characters long.

**Output:** Reports-ready count, target currency and one `normalisation_plan` artifact.

### 4.2 `standardize_identifiers`

**Plain-language definition:** Checks whether an entity TIN contains leading/trailing spaces or lowercase characters and shows the trimmed, uppercase form that would be canonical.

**Important current behaviour:** It does **not** rewrite the source TIN. It reports that standardisation is needed and supplies a preview.

**Parameters:** None.

**Finding raised:** `IDENTIFIER_NOT_STANDARD` with severity `warning`, scoped to the entity, with `canonical_preview` in the evidence.

**Output:** Entity count and zero or more findings.

## 5. Stage 03 — entity and reference enrichment readiness

### 5.1 `resolve_entity`

**Plain-language definition:** Assesses whether constituent entities can be linked deterministically by checking for a TIN.

**Important current behaviour:** It does not perform fuzzy matching, create a TIN or change the entity. It identifies missing deterministic link keys.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `require_tin` | boolean | `true` | When true, raise a warning for each entity without a TIN. When false, the current rule raises no missing-TIN warning. |

**Finding raised:** `ENTITY_TIN_UNAVAILABLE` with severity `warning`, scoped to the entity.

**Output:** Entity count and zero or more findings.

### 5.2 `enrich_jurisdiction_reference`

**Plain-language definition:** Checks that jurisdiction values on CbCR metric rows are represented as two-character codes.

**Important current behaviour:** Despite its name, it currently validates code shape only. It does not perform a complete ISO-code lookup or add jurisdiction reference attributes.

**Parameters:** None.

**Finding raised:** `INVALID_JURISDICTION` with severity `error` when the value is not two characters long.

**Output:** Metric-row count and zero or more findings.

## 6. Stage 04 — substantive data-quality checks

### 6.1 `check_completeness`

**Plain-language definition:** For every report/jurisdiction metric row, checks that each configured canonical metric has a value.

| Parameter | Type | Default | Meaning |
|---|---:|---|---|
| `required_metrics` | array of strings | `['revenue', 'profit_before_tax', 'employees']` | Canonical metric attributes that must not be null. Valid names must exist on the canonical metric model. |

**Finding raised:** `REQUIRED_METRIC_MISSING` with severity `error`, separately for each affected report/jurisdiction. Evidence lists the missing metric names.

**Output:** The required-metric list and zero or more findings.

### 6.2 `check_rpt_share_threshold`

**Plain-language definition:** Calculates related-party revenue divided by total revenue for each jurisdiction row and warns when the share is above the configured limit.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `maximum_related_share` | number | `0.9` | Maximum acceptable related-party share. `0.9` means 90%. The rule uses a strict “greater than” comparison. |

Rows with zero/missing total revenue or missing related-party revenue are not evaluated by this rule.

**Finding raised:** `RELATED_REVENUE_SHARE_HIGH` with severity `warning`, with the calculated share and limit in evidence.

**Output:** Applied threshold and zero or more findings.

## 7. Stage 05 — CbCR-only risk screening

### 7.1 `analyze_profit_presence_mismatch`

**Plain-language definition:** Finds jurisdictions that report a high profit-before-tax margin but very few employees. This is an initial risk indicator that profit may be disproportionate to local operating presence.

The rule calculates `profit_before_tax / revenue` and raises a finding when the margin is greater than or equal to the margin threshold **and** employees are less than or equal to the employee threshold.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `minimum_profit_margin` | number | `0.25` | Minimum PBT/revenue ratio. `0.25` means 25%. |
| `maximum_employees` | integer | `2` | Largest employee count still regarded as limited presence. |

**Finding raised:** `PROFIT_PRESENCE_MISMATCH` with severity `warning`, with margin and employee count in evidence.

**Output:** Applied margin threshold and zero or more findings. These findings can also be used to scope `load_domestic_risk_context`.

### 7.2 `analyze_etr_outlier`

**Plain-language definition:** Finds profitable jurisdictions whose reported effective tax rate is below a chosen threshold.

For positive profit before tax, the rule calculates tax divided by profit. It uses income tax accrued when available; otherwise it uses income tax paid; otherwise zero.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `minimum_etr` | number | `0.05` | Minimum acceptable effective tax rate. `0.05` means 5%. The finding is raised below, not equal to, the threshold. |

**Finding raised:** `LOW_EFFECTIVE_TAX_RATE` with severity `warning`, with calculated ETR and threshold in evidence.

**Output:** Applied ETR threshold and zero or more findings.

## 8. Stage 06 — scoring and domestic-data risk analysis

### 8.1 `cross_match_domestic_turnover`

**Plain-language definition:** Counts CbCR jurisdiction rows available for a chosen domestic jurisdiction and creates a neutral request artifact for a future domestic-turnover adapter.

**Important current behaviour:** It does **not** yet fetch domestic turnover or compare the CbCR and domestic values. An output status of `awaiting_domestic_source_adapter` is expected.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `domestic_jurisdiction` | string | `IN` | Two-letter jurisdiction whose CbCR rows are to be prepared for domestic cross-matching. Converted to uppercase. |

**Output:** Number of canonical rows available and a `cross_match_request` artifact.

### 8.2 `score_risk_components`

**Plain-language definition:** Creates a simple explainable score for each report based on the number of its jurisdiction rows whose cash-tax ETR is below 5%.

Each qualifying row adds 25 points, capped at 100. This rule uses income tax **paid**, not accrued. The 5% and 25-point values are currently fixed in code.

**Parameters:** None.

**Output:** One `risk_component_score` artifact per report, containing `score` and `component_count`. It does not raise findings.

### 8.3 `load_domestic_risk_context`

**Plain-language definition:** Uses the findings from a completed profit/presence screen to identify relevant CbCR reports, links their entities to domestic TINs above the confidence threshold, fetches reduced domestic financial/interest/payment data, and stores an immutable reusable context.

This is the explicit two-step route: CbCR screen first, domestic retrieval second.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `screening_run_id` | string | empty | **Required in practice.** Run ID of a completed `analyze_profit_presence_mismatch` child run for this dataset/version. Only reports with findings in that run are included. |
| `fiscal_year` | integer | `2025` | Domestic fiscal year to retrieve. The registered catalogue supplies 2025 when the user omits this parameter. |
| `match_confidence_floor` | number | `0.85` | Minimum pre-stored entity-link confidence accepted. `0.85` means 85%. |

**Output:** A stored domestic context with a `context_id`, screened report IDs, entity links, financial summaries, interest summaries and aggregated outbound payments. No risk conclusion is made by this function itself.

### 8.4 `analyze_outbound_low_substance_payments`

**Plain-language definition:** Combines domestic outbound-payment data with CbCR data. It flags a material related-party payment when the payee jurisdiction has either low employee presence or a low CbCR ETR.

The function also calculates the payment/domestic-turnover ratio when domestic revenue is available. Its explainable score starts at 35, adds 25 for low headcount, 25 for low ETR and 15 when payment exceeds 10% of turnover, capped at 100.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `domestic_context_id` | string | empty | ID returned by `load_domestic_risk_context`. If blank, orchestration performs a fresh domestic reduction for the current dataset. |
| `fiscal_year` | integer | `2025` | Domestic fiscal year used when a fresh reduction is performed. |
| `min_payment_amount` | number | `1000000` | Minimum aggregated related-party outbound gross payment to evaluate. |
| `low_tax_etr_threshold` | number | `0.1` | CbCR ETR below which the payee jurisdiction is treated as low-tax. `0.1` means 10%. |
| `substance_employee_threshold` | integer | `15` | Employee count at or below which the payee jurisdiction is treated as low-substance. |
| `match_confidence_floor` | number | `0.85` | Minimum domestic entity-link confidence for a fresh reduction. |

**Finding raised:** `ANALYZE_OUTBOUND_LOW_SUBSTANCE_PAYMENTS` with severity `warning`, scoped to report, linked entity and payee jurisdiction.

**Output evidence:** Payment nature and amount, payment/turnover ratio, payee employees, payee ETR, link confidence and score. The finding includes an appropriate-use notice stating that it is for risk/case selection, not a tax adjustment.

### 8.5 `analyze_interest_stripping`

**Plain-language definition:** Combines domestic financial and related-party interest data with CbCR information to identify possible interest-stripping or thin-capitalisation risk.

The function calculates:

- EBITDA as domestic PBT + total interest expense + depreciation/amortisation;
- related-party interest / EBITDA;
- closing related-party borrowings / domestic equity; and
- whether an interest payment goes to a CbCR jurisdiction below the low-tax ETR threshold.

A finding is raised if material related-party interest is present and any of the three risk tests is met. The score adds 45 for excessive interest/EBITDA, 30 for excessive debt/equity and 25 for a low-tax finance hub, capped at 100.

| Parameter | Type | Default | Meaning |
|---|---:|---:|---|
| `domestic_context_id` | string | empty | Reusable stored context ID. If blank, orchestration performs a fresh domestic reduction. |
| `fiscal_year` | integer | `2025` | Domestic fiscal year used for a fresh reduction. |
| `interest_ebitda_cap` | number | `0.3` | Related-party interest/EBITDA threshold. `0.3` means 30%; the rule tests for a value above the cap. |
| `debt_equity_cap` | number | `2.0` | Related-party debt/equity threshold; `2.0` means 2:1. |
| `min_interest_amount` | number | `1000000` | Minimum related-party interest expense required before the entity is assessed. |
| `low_tax_etr_threshold` | number | `0.1` | ETR threshold for a low-tax finance-hub jurisdiction. |
| `match_confidence_floor` | number | `0.85` | Minimum domestic entity-link confidence for a fresh reduction. |

**Finding raised:** `ANALYZE_INTEREST_STRIPPING` with severity `warning`, scoped to report and linked entity.

**Output evidence:** Related interest, EBITDA, interest/EBITDA, related debt/equity, low-tax-hub flag, link confidence and score, plus the appropriate-use notice.

## 9. Stage 07 — case-review preparation

### 9.1 `generate_case_candidates`

**Plain-language definition in PostgreSQL:** Reads the exact risk results contained in an approved Risk Result Set, applies optional score/severity/rule filters, groups the retained results by report and entity, and creates traceable candidates for human review.

Before running it, the risk analyst must create a Risk Result Set from selected successful risk runs and approve/freeze that set. It must belong to the same risk-ready dataset/version.

| Parameter | Type | Default | Meaning |
|---|---:|---|---|
| `risk_result_set_id` | string | empty | **Required in PostgreSQL.** ID of the approved Risk Result Set to consume. |
| `minimum_risk_score` | number | `0` | Keep a risk result when its normalized score is at least this value. Scores in the range 0–1 are converted to 0–100. |
| `allowed_severities` | array of strings | `[]` | Optional severity allow-list, such as `['warning']`. Empty means all severities. |
| `allowed_rules` | array of strings | `[]` | Optional function/rule-code allow-list. Empty means all rules in the approved set. |
| `minimum_profit_margin` | number | `0.4` | Legacy SQLite compatibility parameter. It is ignored by the governed PostgreSQL selection service when `risk_result_set_id` is used. |

**Output:** One `case_candidate` artifact per retained report/entity, including maximum score, source risk-result IDs, source run IDs, source rules, the approved selection policy and full evidence. These become a selection batch for human decisions.

### 9.2 `create_selection_report`

**Plain-language definition:** Creates a minimal listing of every report in the input dataset, with report ID, reporting-entity name and period-end date.

**Important current behaviour:** This is a dataset listing artifact. It is not the final list of human-selected cases, and it does not generate a PDF or spreadsheet.

**Parameters:** None.

**Output:** One `selection_report` artifact containing the report rows.

## 10. API parameter format

For `POST /api/v1/dataset-runs`, parameters are nested under the selected function code. A simple risk run is:

```json
{
  "dataset_id": "<risk-ready-dataset-id>",
  "dataset_version": 1,
  "input_zone": "risk_ready",
  "report_ids": null,
  "functions": ["analyze_etr_outlier"],
  "parameters": {
    "analyze_etr_outlier": {
      "minimum_etr": 0.05
    }
  },
  "purpose": "risk_assessment"
}
```

Several independent functions of the same purpose can be queued together:

```json
{
  "dataset_id": "<canonical-dataset-id>",
  "dataset_version": 1,
  "input_zone": "canonical",
  "report_ids": null,
  "functions": ["check_completeness", "check_rpt_share_threshold"],
  "parameters": {
    "check_completeness": {
      "required_metrics": ["revenue", "profit_before_tax", "employees"]
    },
    "check_rpt_share_threshold": {
      "maximum_related_share": 0.9
    }
  },
  "purpose": "data_quality"
}
```

Functions with no parameters may either be omitted from the `parameters` object or supplied with an empty object.

## 11. Current functional boundaries to remember

1. `normalize_currency` and `standardize_identifiers` identify or plan transformations; they do not rewrite the canonical source values.
2. `enrich_jurisdiction_reference` validates two-character code shape; it is not yet a reference-data enrichment lookup.
3. `cross_match_domestic_turnover` creates an adapter request only; the two newer domestic functions perform actual combined-source analysis.
4. `load_domestic_risk_context` is the only function whose intended route explicitly depends on findings from a named earlier screening run.
5. `generate_case_candidates` uses approved, frozen risk evidence in PostgreSQL. It does not simply re-run a profit-margin test.
6. A successful run with an empty findings array means the function executed but found no record that met its finding condition.

## 12. Code locations

- Function definitions and default parameters: `platform/cbcr_platform/bootstrap.py`
- PostgreSQL domestic-function definitions: `platform/cbcr_platform_pg/bootstrap.py`
- Core function implementations: `platform/cbcr_platform/function_library.py`
- PostgreSQL run validation/orchestration: `platform/cbcr_platform_pg/runs.py`
- Domestic-source reduction boundary: `platform/cbcr_platform_pg/domestic.py`
- Governed PostgreSQL case generation: `platform/cbcr_platform_pg/case_selection.py`
- Function catalogue API: `GET /api/v1/functions`
