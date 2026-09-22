"""Repository boundary for domestic-data reduction.  Replace this adapter, not rules."""
from __future__ import annotations
from typing import Any
from decimal import Decimal
from .database import PostgreSQLDatabase

class DomesticRiskRepository:
    def __init__(self, db: PostgreSQLDatabase): self.db = db

    def reduce(self, reports: list[Any], fiscal_year: int, confidence_floor: float) -> dict[str, Any]:
        wanted = {(r.report_id, e.entity_id) for r in reports for e in r.entities}
        links = [row for row in self.db.all("SELECT * FROM cbcr_risk.domestic_entity_link WHERE confidence >= %s", (confidence_floor,))
                 if (row['report_id'], row['cbc_entity_id']) in wanted]
        tins = [row['domestic_tin'] for row in links]
        if not tins: return {'links': [], 'financials': [], 'interest': [], 'payments': []}
        key_csv = ",".join(tins)
        return {
            'links': links,
            'financials': self.db.all("SELECT * FROM cbcr_domestic_demo.entity_financial_summary WHERE domestic_tin=ANY(string_to_array(%s, ',')) AND fiscal_year=%s", (key_csv, fiscal_year)),
            'interest': self.db.all("SELECT * FROM cbcr_domestic_demo.entity_interest_summary WHERE domestic_tin=ANY(string_to_array(%s, ',')) AND fiscal_year=%s", (key_csv, fiscal_year)),
            'payments': self.db.all("""SELECT domestic_tin,payee_jurisdiction,payment_nature,SUM(gross_amount) gross_amount,
              SUM(tax_withheld) tax_withheld,COUNT(*) payment_count,COUNT(DISTINCT payee_identifier) distinct_payee_count,
              BOOL_OR(is_associated_enterprise) any_related_party
              FROM cbcr_domestic_demo.outbound_payment WHERE domestic_tin=ANY(string_to_array(%s, ',')) AND fiscal_year=%s
              GROUP BY domestic_tin,payee_jurisdiction,payment_nature""", (key_csv, fiscal_year)),
        }

    @staticmethod
    def json_ready(value: Any) -> Any:
        if isinstance(value, Decimal): return float(value)
        if isinstance(value, list): return [DomesticRiskRepository.json_ready(v) for v in value]
        if isinstance(value, dict): return {k: DomesticRiskRepository.json_ready(v) for k, v in value.items()}
        return value
