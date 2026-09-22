from __future__ import annotations

from typing import Any

from .contracts import CanonicalEntity, CanonicalMetric, CanonicalReport


DESCRIPTIONS = {
    "report_id": "Stable jurisdiction-side identifier for one CbCR report.",
    "message_ref_id": "CbCR message reference used for exchange and correction lineage.",
    "reporting_entity_id": "Stable identifier of the reporting entity.",
    "reporting_entity_name": "Legal or reported name of the reporting entity.",
    "reporting_period_end": "End date of the reporting fiscal period.",
    "reporting_currency": "ISO-style currency code used by reported monetary amounts.",
    "receiving_jurisdiction": "Jurisdiction receiving or processing the report.",
    "entity_id": "Stable constituent-entity identifier within jurisdiction processing.",
    "tax_jurisdiction": "Jurisdiction in which the constituent entity is tax resident.",
    "tin": "Tax identification number where supplied and legally usable.",
    "jurisdiction": "Jurisdiction to which the aggregate metrics relate.",
    "currency_code": "Representative currency for the jurisdiction aggregate, when available.",
    "currency_by_measure": "Lossless map from each monetary metric to its XML currCode value.",
    "revenue": "Total revenue for the jurisdiction aggregate.",
    "profit_before_tax": "Profit or loss before income tax.",
    "income_tax_paid": "Income tax paid on a cash basis.",
    "income_tax_accrued": "Current-year income tax accrued.",
    "employees": "Number of employees or full-time equivalents.",
    "tangible_assets": "Tangible assets other than cash and cash equivalents.",
}


def canonical_dictionary() -> list[dict[str, Any]]:
    values = []
    for logical_object, model, excluded in (
        ("report", CanonicalReport, {"entities", "metrics"}),
        ("entity", CanonicalEntity, set()),
        ("metric", CanonicalMetric, set()),
    ):
        for name, field in model.model_fields.items():
            if name in excluded:
                continue
            values.append({
                "logical_object": logical_object, "canonical_field": name,
                "type": str(field.annotation), "required": field.is_required(),
                "description": DESCRIPTIONS.get(name, f"Canonical {name.replace('_', ' ')}."),
            })
    return values
