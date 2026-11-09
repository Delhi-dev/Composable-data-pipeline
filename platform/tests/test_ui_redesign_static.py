from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "cbcr_platform" / "web"


def test_standard_and_advanced_interfaces_remain_separate():
    standard = (WEB / "standard.html").read_text(encoding="utf-8")
    advanced = (WEB / "index.html").read_text(encoding="utf-8")
    assert "/assets/app/main.js" in standard
    assert 'id="view"' in standard
    assert "/assets/niche.js" in advanced
    assert 'id="work" class="view active"' in advanced


def test_standard_ui_modules_cover_the_governed_workflow():
    main = (WEB / "app" / "main.js").read_text(encoding="utf-8")
    for module in (
        "home", "lifecycle", "workspace", "runs", "cases", "reports",
        "oversight", "settings", "reference",
    ):
        assert f'./pages/{module}.js' in main
    cases = (WEB / "app" / "pages" / "cases.js").read_text(encoding="utf-8")
    assert "risk_result_set_id" in cases
    assert "generate_case_candidates" in cases
    assert "/finalize" in cases


def test_demo_impersonation_is_runtime_gated_in_standard_shell():
    shell = (WEB / "app" / "shell.js").read_text(encoding="utf-8")
    assert "Acting as" not in shell
    assert "ui_impersonation" in shell
    assert "data-actor-switch" in shell
    assert "Advanced interface" in shell


def test_reviewed_blocking_contracts_are_reflected_in_ui_code():
    ui = (WEB / "app" / "ui.js").read_text(encoding="utf-8")
    workspace = (WEB / "app" / "pages" / "workspace.js").read_text(encoding="utf-8")
    cases = (WEB / "app" / "pages" / "cases.js").read_text(encoding="utf-8")
    assert ui.count("formnovalidate") >= 2
    assert "reporting_period_end" in workspace
    assert "value.dataset" in workspace and "value.promotions" in workspace
    assert "requested_at||r.created_at" in workspace
    assert "decision_rationale" in cases
    assert "batchStatus!=='open'" in cases


def test_standard_ui_includes_guided_workflow_controls():
    lifecycle = (WEB / "app" / "pages" / "lifecycle.js").read_text(encoding="utf-8")
    workspace = (WEB / "app" / "pages" / "workspace.js").read_text(encoding="utf-8")
    oversight = (WEB / "app" / "pages" / "oversight.js").read_text(encoding="utf-8")
    assert "lot-stages" in lifecycle
    assert "Evaluate DQ gate" in workspace
    assert "screening_run_id" in workspace and "domestic_context_id" in workspace
    assert "End-to-end audit-case lineage" in oversight


def test_report_print_action_downloads_server_generated_pdf():
    reports = (WEB / "app" / "pages" / "reports.js").read_text(encoding="utf-8")
    api = (WEB.parents[1] / "cbcr_platform_pg" / "api.py").read_text(encoding="utf-8")
    assert "window.print()" not in reports
    assert "Download PDF report" in reports
    assert "${reportCode}.pdf" in reports
    assert 'reports/selected-cases.pdf' in api
    assert 'reports/lineage.pdf' in api
