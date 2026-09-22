from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from .canonical import CanonicalDataAPI
from .contracts import Finding, FunctionResult


Handler = Callable[[CanonicalDataAPI, dict[str, Any]], FunctionResult]


def _finding(code: str, report_id: str, severity: str, finding_code: str,
             message: str, evidence: dict[str, Any], **scope: Any) -> Finding:
    return Finding(function_code=code, report_id=report_id, severity=severity,
                   code=finding_code, message=message, evidence=evidence, **scope)


def validate_receipt_identity(api: CanonicalDataAPI, _: dict[str, Any]) -> FunctionResult:
    findings = []
    for report in api.list_reports():
        if not report.message_ref_id or not report.reporting_entity_id:
            findings.append(_finding("validate_receipt_identity", report.report_id, "error",
                "RECEIPT_IDENTITY_MISSING", "Receipt identity is incomplete.",
                {"message_ref_present": bool(report.message_ref_id),
                 "reporting_entity_present": bool(report.reporting_entity_id)}))
    return FunctionResult(summary={"reports_checked": len(api.list_reports())}, findings=findings)


def detect_duplicate_report(api: CanonicalDataAPI, _: dict[str, Any]) -> FunctionResult:
    seen: dict[tuple[str, str, str], str] = {}
    findings = []
    for report in api.list_reports():
        key = (report.message_ref_id, report.reporting_entity_id,
               report.reporting_period_end.isoformat())
        if key in seen:
            findings.append(_finding("detect_duplicate_report", report.report_id, "error",
                "DUPLICATE_REPORT", "A report with the same business identity exists.",
                {"duplicate_of": seen[key]}))
        else:
            seen[key] = report.report_id
    return FunctionResult(summary={"unique_business_keys": len(seen)}, findings=findings)


def normalize_currency(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    target = str(params.get("target_currency", "EUR")).upper()
    unsupported = [r.report_id for r in api.list_reports()
                   if not r.reporting_currency or len(r.reporting_currency) != 3]
    findings = [_finding("normalize_currency", rid, "error", "INVALID_CURRENCY_CODE",
                         "Reporting currency is not a three-letter code.", {},)
                for rid in unsupported]
    return FunctionResult(summary={"target_currency": target,
        "reports_ready": len(api.list_reports()) - len(unsupported)}, findings=findings,
        artifacts=[{"type": "normalisation_plan", "target_currency": target}])


def standardize_identifiers(api: CanonicalDataAPI, _: dict[str, Any]) -> FunctionResult:
    findings = []
    for report in api.list_reports():
        for entity in report.entities:
            if entity.tin and entity.tin != entity.tin.strip().upper():
                findings.append(_finding("standardize_identifiers", report.report_id, "warning",
                    "IDENTIFIER_NOT_STANDARD", "TIN requires trim/uppercase standardisation.",
                    {"canonical_preview": entity.tin.strip().upper()}, entity_id=entity.entity_id))
    return FunctionResult(summary={"entities_checked": len(api.list_entities())}, findings=findings)


def resolve_entity(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    require_tin = bool(params.get("require_tin", True))
    findings = []
    for report in api.list_reports():
        for entity in report.entities:
            if require_tin and not entity.tin:
                findings.append(_finding("resolve_entity", report.report_id, "warning",
                    "ENTITY_TIN_UNAVAILABLE", "Entity cannot be deterministically linked without a TIN.",
                    {"entity_name": entity.name}, entity_id=entity.entity_id))
    return FunctionResult(summary={"entities_considered": len(api.list_entities())}, findings=findings)


def enrich_jurisdiction_reference(api: CanonicalDataAPI, _: dict[str, Any]) -> FunctionResult:
    invalid = []
    for report in api.list_reports():
        for metric in report.metrics:
            if len(metric.jurisdiction) != 2:
                invalid.append(_finding("enrich_jurisdiction_reference", report.report_id, "error",
                    "INVALID_JURISDICTION", "Jurisdiction must use a two-letter code.",
                    {"value": metric.jurisdiction}, jurisdiction=metric.jurisdiction))
    return FunctionResult(summary={"metric_rows_checked": sum(len(r.metrics) for r in api.list_reports())}, findings=invalid)


def check_completeness(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    fields = params.get("required_metrics", ["revenue", "profit_before_tax", "employees"])
    findings = []
    for report in api.list_reports():
        for metric in report.metrics:
            missing = [name for name in fields if getattr(metric, name, None) is None]
            if missing:
                findings.append(_finding("check_completeness", report.report_id, "error",
                    "REQUIRED_METRIC_MISSING", "Required jurisdiction metrics are missing.",
                    {"missing": missing}, jurisdiction=metric.jurisdiction))
    return FunctionResult(summary={"required_metrics": fields}, findings=findings)


def check_rpt_share_threshold(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    maximum = Decimal(str(params.get("maximum_related_share", 0.9)))
    findings = []
    for report in api.list_reports():
        for metric in report.metrics:
            if metric.revenue and metric.related_revenue is not None:
                share = metric.related_revenue / metric.revenue
                if share > maximum:
                    findings.append(_finding("check_rpt_share_threshold", report.report_id, "warning",
                        "RELATED_REVENUE_SHARE_HIGH", "Related-party revenue share exceeds the parameter.",
                        {"share": float(share), "maximum": float(maximum)}, jurisdiction=metric.jurisdiction))
    return FunctionResult(summary={"maximum_related_share": float(maximum)}, findings=findings)


def analyze_profit_presence_mismatch(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    ratio = Decimal(str(params.get("minimum_profit_margin", 0.25)))
    max_employees = int(params.get("maximum_employees", 2))
    findings = []
    for report in api.list_reports():
        for metric in report.metrics:
            margin = (metric.profit_before_tax or 0) / metric.revenue if metric.revenue else 0
            if margin >= ratio and (metric.employees or 0) <= max_employees:
                findings.append(_finding("analyze_profit_presence_mismatch", report.report_id, "warning",
                    "PROFIT_PRESENCE_MISMATCH", "High profit margin is reported with limited employee presence.",
                    {"margin": float(margin), "employees": metric.employees}, jurisdiction=metric.jurisdiction))
    return FunctionResult(summary={"minimum_profit_margin": float(ratio)}, findings=findings)


def analyze_etr_outlier(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    minimum = Decimal(str(params.get("minimum_etr", 0.05)))
    findings = []
    for report in api.list_reports():
        for metric in report.metrics:
            if metric.profit_before_tax and metric.profit_before_tax > 0:
                etr = (metric.income_tax_accrued or metric.income_tax_paid or 0) / metric.profit_before_tax
                if etr < minimum:
                    findings.append(_finding("analyze_etr_outlier", report.report_id, "warning",
                        "LOW_EFFECTIVE_TAX_RATE", "Effective tax rate is below the configured threshold.",
                        {"etr": float(etr), "minimum": float(minimum)}, jurisdiction=metric.jurisdiction))
    return FunctionResult(summary={"minimum_etr": float(minimum)}, findings=findings)


def cross_match_domestic_turnover(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    domestic = str(params.get("domestic_jurisdiction", "IN")).upper()
    rows = sum(len(api.get_jurisdiction_metrics(r.report_id, domestic)) for r in api.list_reports())
    return FunctionResult(summary={"domestic_jurisdiction": domestic, "canonical_rows_available": rows},
        artifacts=[{"type": "cross_match_request", "jurisdiction": domestic,
                    "status": "awaiting_domestic_source_adapter"}])


def score_risk_components(api: CanonicalDataAPI, _: dict[str, Any]) -> FunctionResult:
    artifacts = []
    for report in api.list_reports():
        metrics = report.metrics
        low_etr = sum(1 for m in metrics if m.profit_before_tax and
                      (m.income_tax_paid or 0) / m.profit_before_tax < Decimal("0.05"))
        artifacts.append({"type": "risk_component_score", "report_id": report.report_id,
                          "score": min(100, low_etr * 25), "component_count": low_etr})
    return FunctionResult(summary={"reports_scored": len(artifacts)}, artifacts=artifacts)

def _risk_finding(code: str, report_id: str, entity_id: str, jurisdiction: str, score: float, message: str, evidence: dict[str, Any]) -> Finding:
    evidence["score"] = score
    evidence["appropriate_use_notice"] = "Risk assessment and case selection only; not a basis for a tax adjustment."
    return _finding(code, report_id, "warning", code.upper(), message, evidence, entity_id=entity_id, jurisdiction=jurisdiction)

def load_domestic_risk_context(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    context = params.get("__domestic", {})
    return FunctionResult(summary={"screened_reports": len(params.get("__screened_report_ids", [])), "matched_entities": len(context.get("links", []))}, artifacts=[{"type":"domestic_risk_context","screening_run_id":params.get("screening_run_id"),"fiscal_year":params.get("fiscal_year"),"report_ids":params.get("__screened_report_ids", []),"payload":context}])

def analyze_outbound_low_substance_payments(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    domestic = params.get("__domestic", {}); minimum = Decimal(str(params.get("min_payment_amount", 1000000)))
    low_tax = Decimal(str(params.get("low_tax_etr_threshold", .10))); headcount = int(params.get("substance_employee_threshold", 15))
    links = {r["domestic_tin"]: r for r in domestic.get("links", [])}; financials = {r["domestic_tin"]: r for r in domestic.get("financials", [])}
    findings=[]
    for flow in domestic.get("payments", []):
        link=links.get(flow["domestic_tin"]); report=next((r for r in api.list_reports() if link and r.report_id==link["report_id"]), None)
        if not report or not flow["any_related_party"] or flow["gross_amount"] < minimum: continue
        metric=next((m for m in report.metrics if m.jurisdiction==flow["payee_jurisdiction"]), None)
        if not metric: continue
        etr=(metric.income_tax_accrued or 0)/metric.profit_before_tax if metric.profit_before_tax and metric.profit_before_tax>0 else None
        if not ((metric.employees or 0)<=headcount or (etr is not None and etr<low_tax)): continue
        fin=financials.get(flow["domestic_tin"],{}); ratio=flow["gross_amount"]/fin["revenue"] if fin.get("revenue") else None
        score=min(100, 35 + (25 if (metric.employees or 0)<=headcount else 0) + (25 if etr is not None and etr<low_tax else 0) + (15 if ratio and ratio>.10 else 0))
        findings.append(_risk_finding("analyze_outbound_low_substance_payments",report.report_id,link["cbc_entity_id"],metric.jurisdiction,float(score),"Material related-party outbound payment is directed to a low-tax or low-substance group jurisdiction.",{"payment_nature":flow["payment_nature"],"gross_amount":float(flow["gross_amount"]),"payment_to_turnover_ratio":float(ratio) if ratio else None,"payee_employees":metric.employees,"payee_etr":float(etr) if etr is not None else None,"match_confidence":float(link["confidence"])}))
    return FunctionResult(summary={"matched_entities":len(links),"findings":len(findings)},findings=findings)

def analyze_interest_stripping(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    domestic=params.get("__domestic",{}); cap=Decimal(str(params.get("interest_ebitda_cap",.30))); debtcap=Decimal(str(params.get("debt_equity_cap",2))); minimum=Decimal(str(params.get("min_interest_amount",1000000))); lowtax=Decimal(str(params.get("low_tax_etr_threshold",.10)))
    links={r["domestic_tin"]:r for r in domestic.get("links",[])}; fins={r["domestic_tin"]:r for r in domestic.get("financials",[])}; interest={r["domestic_tin"]:r for r in domestic.get("interest",[])}; findings=[]
    for tin, link in links.items():
        fin=fins.get(tin); intr=interest.get(tin); report=next((r for r in api.list_reports() if r.report_id==link["report_id"]),None)
        if not fin or not intr or not report or intr["interest_expense_related"]<minimum: continue
        ebitda=fin["profit_before_tax"]+fin["interest_expense_total"]+fin["depreciation_amortisation"]; ratio=intr["interest_expense_related"]/ebitda if ebitda>0 else None; de=intr["closing_related_borrowings"]/fin["equity"] if fin["equity"]>0 else None
        hub=False
        for flow in domestic.get("payments",[]):
            if flow["domestic_tin"]==tin and flow["payment_nature"]=="INTEREST":
                m=next((m for m in report.metrics if m.jurisdiction==flow["payee_jurisdiction"]),None)
                hub = hub or bool(m and m.profit_before_tax>0 and (m.income_tax_accrued or 0)/m.profit_before_tax<lowtax)
        if not ((ratio and ratio>cap) or (de and de>debtcap) or hub): continue
        score=min(100, (45 if ratio and ratio>cap else 0)+(30 if de and de>debtcap else 0)+(25 if hub else 0))
        findings.append(_risk_finding("analyze_interest_stripping",report.report_id,link["cbc_entity_id"],None,float(score),"Related-party interest indicates potential thin-capitalisation or interest-stripping risk.",{"related_interest":float(intr["interest_expense_related"]),"ebitda":float(ebitda),"interest_to_ebitda":float(ratio) if ratio else None,"related_debt_to_equity":float(de) if de else None,"low_tax_finance_hub":hub,"match_confidence":float(link["confidence"])}))
    return FunctionResult(summary={"matched_entities":len(links),"findings":len(findings)},findings=findings)


def generate_case_candidates(api: CanonicalDataAPI, params: dict[str, Any]) -> FunctionResult:
    threshold = float(params.get("minimum_profit_margin", 0.4))
    candidates = []
    for report in api.list_reports():
        max_margin = max((float((m.profit_before_tax or 0) / m.revenue)
                          for m in report.metrics if m.revenue), default=0)
        if max_margin >= threshold:
            candidates.append({"type": "case_candidate", "report_id": report.report_id,
                               "reason_code": "HIGH_MARGIN", "maximum_margin": max_margin})
    return FunctionResult(summary={"candidate_count": len(candidates)}, artifacts=candidates)


def create_selection_report(api: CanonicalDataAPI, _: dict[str, Any]) -> FunctionResult:
    rows = [{"report_id": r.report_id, "reporting_entity": r.reporting_entity_name,
             "period_end": r.reporting_period_end.isoformat()} for r in api.list_reports()]
    return FunctionResult(summary={"report_count": len(rows)},
                          artifacts=[{"type": "selection_report", "rows": rows}])


HANDLERS: dict[str, Handler] = {
    handler.__name__: handler for handler in (
        validate_receipt_identity, detect_duplicate_report, normalize_currency,
        standardize_identifiers, resolve_entity, enrich_jurisdiction_reference,
        check_completeness, check_rpt_share_threshold, analyze_profit_presence_mismatch,
        analyze_etr_outlier, cross_match_domestic_turnover, score_risk_components,
        load_domestic_risk_context, analyze_outbound_low_substance_payments, analyze_interest_stripping,
        generate_case_candidates, create_selection_report,
    )
}
