from cbcr_platform_pg.pdf_reports import lineage_pdf, selected_cases_pdf


def sample_selected_report():
    case = {
        "audit_case_id": "ac000001-2222-4333-8444-555555555555",
        "candidate_id": "ca000001-2222-4333-8444-555555555555",
        "dataset_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        "dataset_version": 1,
        "report_id": "Synthetic_2",
        "entity_id": "ENT-IN-001",
        "entity_name": "Example India Services Pvt Ltd",
        "score": 0.87,
        "reason_code": "PROFIT_PRESENCE_MISMATCH",
        "decision": "selected",
        "decision_rationale": "High profit with limited employee presence; refer for detailed review.",
        "decided_by": "case.reviewer",
        "decided_at": "2026-11-09T09:35:00+00:00",
        "status": "ready_for_audit",
        "external_reference": "AUDIT-DEMO-001",
        "finalization_rationale": "All candidate evidence reviewed and approved.",
        "source_functions": [
            "analyze_profit_presence_mismatch",
            "analyze_interest_stripping",
        ],
        "source_run_ids": [
            "12345678-1234-4234-8234-123456789012",
            "87654321-4321-4321-8321-210987654321",
        ],
        "source_document": {
            "source_file_name": "TEST_CbC_v2_0.xml",
            "message_ref_id": "MSG-DEMO-001",
            "xml_document_id": "doc-demo-001",
        },
        "source_risk_results": [
            {
                "rule_code": "PROFIT_PRESENCE_MISMATCH",
                "severity": "high",
                "jurisdiction": "IN",
                "run_id": "12345678-1234-4234-8234-123456789012",
                "result": {"profit_margin": 0.62, "employees": 1},
            },
            {
                "rule_code": "INTEREST_STRIPPING",
                "severity": "medium",
                "jurisdiction": "IN",
                "run_id": "87654321-4321-4321-8321-210987654321",
                "result": {"interest_to_ebitda": 0.48},
            },
        ],
    }
    case_set = {
        "name": "Demonstration audit handoff",
        "case_set_id": "11111111-2222-4333-8444-555555555555",
        "status": "finalized",
        "dataset_id": case["dataset_id"],
        "dataset_version": 1,
        "selection_batch_id": "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff",
        "external_lot_ref": "DEMO-2026-11-01",
        "risk_result_set_name": "Approved combined risk evidence",
        "risk_result_set_status": "approved",
        "finalized_by": "case.reviewer",
        "finalized_at": "2026-11-09T09:45:00+00:00",
    }
    return {
        "report_title": "Final selected cases",
        "generated_at": "2026-11-09T10:15:00+00:00",
        "case_set": case_set,
        "case_count": 1,
        "cases": [case],
    }


def assert_valid_pdf(value: bytes, minimum_pages: int):
    assert value.startswith(b"%PDF-1.4")
    assert value.endswith(b"%%EOF\n")
    assert b"xref\n" in value and b"startxref\n" in value
    assert value.count(b"/Type /Page ") >= minimum_pages
    assert b"/Creator (CbCR Control Plane PDF service)" in value


def test_selected_cases_pdf_is_a_detailed_multi_page_case_report():
    value = selected_cases_pdf(sample_selected_report())
    assert_valid_pdf(value, minimum_pages=3)
    for expected in (
        b"Final selected cases",
        b"Selected-case register",
        b"Example India Services Pvt Ltd",
        b"Human decision",
        b"Risk provenance",
        b"Source document reference",
        b"PROFIT_PRESENCE_MISMATCH",
        b"Page 1 of 3",
    ):
        assert expected in value


def test_lineage_pdf_includes_execution_and_selected_case_context():
    selected = sample_selected_report()
    value = lineage_pdf(
        {
            "generated_at": selected["generated_at"],
            "case_set": selected["case_set"],
            "dataset_ancestry": [
                {
                    "sequence": 1,
                    "zone": "landing",
                    "dataset_id": "d0000001-0000-4000-8000-000000000001",
                    "version": 1,
                    "transition": "origin",
                    "created_at": "2026-11-09T08:00:00+00:00",
                },
                {
                    "sequence": 2,
                    "zone": "risk_ready",
                    "dataset_id": selected["case_set"]["dataset_id"],
                    "version": 1,
                    "transition": "promote_enriched_to_risk_ready",
                    "transition_at": "2026-11-09T08:30:00+00:00",
                },
            ],
            "promotions": [
                {
                    "source_zone": "enriched",
                    "target_zone": "risk_ready",
                    "promotion_id": "p0000001-0000-4000-8000-000000000001",
                    "reason": "Ready for risk analysis",
                }
            ],
            "runs": [
                {
                    "run_id": "12345678-1234-4234-8234-123456789012",
                    "purpose": "risk_assessment",
                    "status": "completed",
                    "function_runs": [
                        {
                            "stage": "05",
                            "function_code": "analyze_profit_presence_mismatch",
                            "function_version": 1,
                            "status": "completed",
                            "parameters": {"minimum_profit_margin": 0.25},
                            "result_summary": {"findings": 1},
                        }
                    ],
                }
            ],
            "selected_cases": selected["cases"],
        }
    )
    assert_valid_pdf(value, minimum_pages=3)
    assert b"Dataset ancestry" in value
    assert b"Function execution register" in value
    assert b"Selected cases carried into the final set" in value
    assert b"analyze_profit_presence_mismatch" in value
