from __future__ import annotations

import json
import textwrap
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable


PAGE_WIDTH = 595.28
PAGE_HEIGHT = 841.89
MARGIN = 40.0
CONTENT_WIDTH = PAGE_WIDTH - (2 * MARGIN)

INK = (0.09, 0.13, 0.11)
MUTED = (0.35, 0.39, 0.36)
PAPER = (0.96, 0.95, 0.91)
PANEL = (0.90, 0.91, 0.87)
ACCENT = (0.21, 0.36, 0.27)
ACCENT_LIGHT = (0.85, 0.90, 0.86)
RULE = (0.66, 0.69, 0.66)
WHITE = (1.0, 1.0, 1.0)


def _plain(value: Any, fallback: str = "-") -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def _ascii(value: Any) -> str:
    return (
        unicodedata.normalize("NFKD", _plain(value))
        .encode("ascii", "replace")
        .decode("ascii")
    )


def _pdf_string(value: Any) -> str:
    return _ascii(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _format_when(value: Any) -> str:
    if not value:
        return "-"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M UTC")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    return str(value)


def _short(value: Any) -> str:
    raw = _plain(value)
    return raw if len(raw) <= 20 else f"{raw[:8]}...{raw[-6:]}"


def _rgb(color: tuple[float, float, float], stroke: bool = False) -> str:
    operator = "RG" if stroke else "rg"
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} {operator}"


class PDFReport:
    """Small dependency-free PDF layout engine for controlled tabular reports."""

    def __init__(self, title: str, subject: str):
        self.title = title
        self.subject = subject
        self.pages: list[list[str]] = []
        self.commands: list[str] = []
        self.y = PAGE_HEIGHT - MARGIN
        self.new_page()

    def new_page(self) -> None:
        if self.commands:
            self.pages.append(self.commands)
        self.commands = []
        self.y = PAGE_HEIGHT - MARGIN
        self.text(MARGIN, self.y, "CBCR CONTROL PLANE", 7.5, bold=True, color=MUTED)
        self.text(PAGE_WIDTH - MARGIN, self.y, "CONTROLLED REPORT", 7, align="right", color=MUTED)
        self.y -= 18
        self.line(MARGIN, self.y, PAGE_WIDTH - MARGIN, self.y, RULE, 0.5)
        self.y -= 18

    def ensure(self, height: float) -> None:
        if self.y - height < 49:
            self.new_page()

    def text(
        self,
        x: float,
        y: float,
        value: Any,
        size: float = 9,
        *,
        bold: bool = False,
        mono: bool = False,
        color: tuple[float, float, float] = INK,
        align: str = "left",
    ) -> None:
        font = "F3" if mono else "F2" if bold else "F1"
        raw = _ascii(value)
        estimated = len(raw) * size * (0.6 if mono else 0.51)
        if align == "right":
            x -= estimated
        elif align == "center":
            x -= estimated / 2
        self.commands.append(
            f"BT /{font} {size:.2f} Tf {_rgb(color)} 1 0 0 1 {x:.2f} {y:.2f} Tm ({_pdf_string(raw)}) Tj ET"
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: tuple[float, float, float] = RULE,
        width: float = 0.5,
    ) -> None:
        self.commands.append(
            f"q {_rgb(color, True)} {width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S Q"
        )

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: tuple[float, float, float] | None = None,
        stroke: tuple[float, float, float] | None = RULE,
        line_width: float = 0.5,
    ) -> None:
        operations = ["q"]
        if fill:
            operations.append(_rgb(fill))
        if stroke:
            operations.extend([_rgb(stroke, True), f"{line_width:.2f} w"])
        paint = "B" if fill and stroke else "f" if fill else "S"
        operations.append(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re {paint} Q")
        self.commands.append(" ".join(operations))

    def wrapped_lines(self, value: Any, width: float, size: float = 9, mono: bool = False) -> list[str]:
        raw = _ascii(value)
        per_line = max(8, int(width / (size * (0.6 if mono else 0.51))))
        lines: list[str] = []
        for paragraph in raw.splitlines() or [""]:
            lines.extend(
                textwrap.wrap(
                    paragraph,
                    width=per_line,
                    break_long_words=True,
                    break_on_hyphens=True,
                    replace_whitespace=False,
                )
                or [""]
            )
        return lines

    def paragraph(
        self,
        value: Any,
        *,
        size: float = 9,
        leading: float = 12,
        bold: bool = False,
        mono: bool = False,
        color: tuple[float, float, float] = INK,
        width: float = CONTENT_WIDTH,
        x: float = MARGIN,
        after: float = 5,
    ) -> None:
        lines = self.wrapped_lines(value, width, size, mono)
        self.ensure((len(lines) * leading) + after)
        for line_value in lines:
            self.text(x, self.y, line_value, size, bold=bold, mono=mono, color=color)
            self.y -= leading
        self.y -= after

    def title_block(self, title: str, description: str) -> None:
        self.paragraph(title, size=23, leading=27, bold=True, after=6)
        self.paragraph(description, size=9, leading=13, color=MUTED, after=10)

    def section(self, title: str) -> None:
        self.ensure(31)
        self.rect(MARGIN, self.y - 17, 4, 20, fill=ACCENT, stroke=None)
        self.text(MARGIN + 11, self.y - 11, title, 13, bold=True, color=ACCENT)
        self.y -= 28

    def metrics(self, values: Iterable[tuple[Any, str]]) -> None:
        items = list(values)
        self.ensure(61)
        gap = 6
        width = (CONTENT_WIDTH - (gap * (len(items) - 1))) / len(items)
        x = MARGIN
        for value, label in items:
            self.rect(x, self.y - 48, width, 48, fill=ACCENT_LIGHT, stroke=ACCENT, line_width=0.6)
            raw_value = _ascii(value)
            value_size = 13 if len(raw_value) <= 12 else 10 if len(raw_value) <= 18 else 8
            value_lines = self.wrapped_lines(raw_value, width - 12, value_size)[:2]
            value_y = self.y - 17 if len(value_lines) == 1 else self.y - 13
            for value_line in value_lines:
                self.text(
                    x + (width / 2),
                    value_y,
                    value_line,
                    value_size,
                    bold=True,
                    color=ACCENT,
                    align="center",
                )
                value_y -= value_size + 1.5
            self.text(x + (width / 2), self.y - 36, _ascii(label).upper(), 6.5, color=MUTED, align="center")
            x += width + gap
        self.y -= 59

    def key_values(self, pairs: Iterable[tuple[str, Any]]) -> None:
        label_width = 124
        value_width = CONTENT_WIDTH - label_width
        for label, value in pairs:
            lines = self.wrapped_lines(value, value_width - 12, 8.2)
            height = max(25, (len(lines) * 10.5) + 10)
            self.ensure(height)
            bottom = self.y - height
            self.rect(MARGIN, bottom, label_width, height, fill=PANEL, stroke=RULE)
            self.rect(MARGIN + label_width, bottom, value_width, height, fill=WHITE, stroke=RULE)
            self.text(MARGIN + 6, self.y - 14, _ascii(label).upper(), 7, bold=True, color=MUTED)
            text_y = self.y - 13
            for line_value in lines:
                self.text(MARGIN + label_width + 6, text_y, line_value, 8.2)
                text_y -= 10.5
            self.y = bottom
        self.y -= 5

    def table(
        self,
        headers: list[str],
        rows: list[list[Any]],
        widths: list[float],
        *,
        font_size: float = 7.2,
    ) -> None:
        def draw_header() -> None:
            height = 24
            x = MARGIN
            for header, width in zip(headers, widths):
                self.rect(x, self.y - height, width, height, fill=ACCENT, stroke=WHITE, line_width=0.25)
                self.text(x + 5, self.y - 15, _ascii(header).upper(), 6.4, bold=True, color=WHITE)
                x += width
            self.y -= height

        self.ensure(50)
        draw_header()
        for index, row in enumerate(rows):
            cell_lines = [self.wrapped_lines(value, width - 10, font_size) for value, width in zip(row, widths)]
            height = max(25, max(len(lines) for lines in cell_lines) * (font_size + 2.5) + 10)
            if self.y - height < 49:
                self.new_page()
                draw_header()
            x = MARGIN
            fill = WHITE if index % 2 == 0 else PAPER
            for lines, width in zip(cell_lines, widths):
                self.rect(x, self.y - height, width, height, fill=fill, stroke=RULE, line_width=0.3)
                line_y = self.y - (font_size + 5)
                for line_value in lines:
                    self.text(x + 5, line_y, line_value, font_size)
                    line_y -= font_size + 2.5
                x += width
            self.y -= height
        self.y -= 6

    def finish(self) -> bytes:
        if self.commands:
            self.pages.append(self.commands)
            self.commands = []
        for number, page in enumerate(self.pages, start=1):
            page.append(f"q {_rgb(RULE, True)} 0.4 w {MARGIN:.2f} 36 m {PAGE_WIDTH - MARGIN:.2f} 36 l S Q")
            page.append(
                f"BT /F1 7 Tf {_rgb(MUTED)} 1 0 0 1 {MARGIN:.2f} 23 Tm (CbCR Control Plane - controlled report) Tj ET"
            )
            footer = f"Page {number} of {len(self.pages)}"
            footer_x = PAGE_WIDTH - MARGIN - (len(footer) * 3.6)
            page.append(
                f"BT /F1 7 Tf {_rgb(MUTED)} 1 0 0 1 {footer_x:.2f} 23 Tm ({footer}) Tj ET"
            )
        return _build_pdf(self.pages, self.title, self.subject)


def _build_pdf(pages: list[list[str]], title: str, subject: str) -> bytes:
    objects: list[bytes | None] = [None]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(None)
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    page_refs: list[int] = []
    for commands in pages:
        page_number = len(objects)
        stream_number = page_number + 1
        page_refs.append(page_number)
        page_object = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH:.2f} {PAGE_HEIGHT:.2f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
            f"/Contents {stream_number} 0 R >>"
        ).encode("ascii")
        stream = "\n".join(commands).encode("ascii", "replace")
        stream_object = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        objects.extend([page_object, stream_object])
    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{number} 0 R' for number in page_refs)}] /Count {len(page_refs)} >>"
    ).encode("ascii")
    info_number = len(objects)
    objects.append(
        (
            f"<< /Title ({_pdf_string(title)}) /Author (CbCR Control Plane) "
            f"/Subject ({_pdf_string(subject)}) /Creator (CbCR Control Plane PDF service) >>"
        ).encode("ascii")
    )
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects[1:], start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(obj or b"")
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects)} /Root 1 0 R /Info {info_number} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _summary_rows(cases: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for index, item in enumerate(cases, start=1):
        score = "-" if item.get("score") is None else f"{float(item['score']):.2f}"
        rows.append(
            [
                index,
                f"{_plain(item.get('entity_name') or item.get('entity_id') or 'Unnamed entity')}\n{_plain(item.get('report_id'))}",
                f"{score}\n{_plain(item.get('reason_code'))}",
                item.get("decision"),
                item.get("status"),
            ]
        )
    return rows


def selected_cases_pdf(report: dict[str, Any]) -> bytes:
    case_set = report.get("case_set") or {}
    cases = report.get("cases") or []
    pdf = PDFReport("Final selected cases", "Final case selection and audit handoff")
    pdf.title_block(
        "Final selected cases",
        f"Controlled case-selection report generated {_format_when(report.get('generated_at'))}. "
        "It records the cases approved for audit handoff, the human rationale and the source risk evidence.",
    )
    pdf.metrics(
        [
            (len(cases), "Selected cases"),
            (case_set.get("status"), "Case-set status"),
            (case_set.get("dataset_version"), "Dataset version"),
            (case_set.get("risk_result_set_status"), "Evidence status"),
        ]
    )
    pdf.section("Case-set details")
    pdf.key_values(
        [
            ("Case-set name", case_set.get("name")),
            ("Case-set ID", case_set.get("case_set_id")),
            ("External lot reference", case_set.get("external_lot_ref")),
            ("Dataset", f"{_plain(case_set.get('dataset_id'))} v{_plain(case_set.get('dataset_version'))}"),
            ("Selection batch", case_set.get("selection_batch_id")),
            ("Approved evidence set", case_set.get("risk_result_set_name") or case_set.get("risk_result_set_id")),
            ("Finalized by / at", f"{_plain(case_set.get('finalized_by') or case_set.get('created_by'))} / {_format_when(case_set.get('finalized_at') or case_set.get('created_at'))}"),
        ]
    )
    pdf.section("Selected-case register")
    if cases:
        pdf.table(
            ["Case", "Entity / report", "Risk", "Decision", "Audit status"],
            _summary_rows(cases),
            [32, 190, 105, 85, 103],
        )
    else:
        pdf.paragraph("This finalized set contains no selected cases.")
    for index, item in enumerate(cases, start=1):
        pdf.new_page()
        pdf.paragraph(f"SELECTED CASE {index} OF {len(cases)}", size=7, bold=True, color=MUTED, after=4)
        pdf.paragraph(
            item.get("entity_name") or item.get("entity_id") or "Unnamed entity",
            size=18,
            leading=21,
            bold=True,
            after=3,
        )
        pdf.paragraph(
            f"Report {_plain(item.get('report_id'))} | Audit case {_plain(item.get('audit_case_id'))}",
            size=8.5,
            color=MUTED,
            after=8,
        )
        pdf.metrics(
            [
                ("-" if item.get("score") is None else f"{float(item['score']):.2f}", "Risk score"),
                (item.get("reason_code"), "Reason code"),
                (item.get("decision"), "Human decision"),
                (item.get("status"), "Audit status"),
            ]
        )
        pdf.section("Case identity and handoff")
        pdf.key_values(
            [
                ("Report ID", item.get("report_id")),
                ("Entity ID", item.get("entity_id")),
                ("Entity name", item.get("entity_name")),
                ("Audit case ID", item.get("audit_case_id")),
                ("Candidate ID", item.get("candidate_id")),
                ("External reference", item.get("external_reference")),
            ]
        )
        pdf.section("Human decision")
        pdf.key_values(
            [
                ("Decision", item.get("decision")),
                ("Rationale", item.get("decision_rationale")),
                ("Decided by", item.get("decided_by")),
                ("Decided at", _format_when(item.get("decided_at"))),
                ("Finalization rationale", item.get("finalization_rationale")),
            ]
        )
        pdf.section("Risk provenance")
        pdf.key_values(
            [
                ("Source functions", ", ".join(item.get("source_functions") or []) or "-"),
                ("Source run IDs", ", ".join(item.get("source_run_ids") or []) or "-"),
            ]
        )
        source_rows = []
        for source in item.get("source_risk_results") or []:
            source_rows.append(
                [
                    source.get("rule_code"),
                    source.get("severity"),
                    source.get("jurisdiction"),
                    _short(source.get("run_id")),
                    json.dumps(source.get("result") or {}, sort_keys=True, default=str),
                ]
            )
        if source_rows:
            pdf.table(
                ["Rule", "Severity", "Jurisdiction", "Source run", "Evidence"],
                source_rows,
                [105, 55, 65, 93, 197],
                font_size=6.5,
            )
        else:
            pdf.paragraph("No source risk-result detail was recorded.", color=MUTED)
        source_document = item.get("source_document") or {}
        if source_document:
            pdf.ensure(120)
            pdf.section("Source document reference")
            pdf.key_values(
                [
                    ("Source file", source_document.get("source_file_name")),
                    ("Message reference", source_document.get("message_ref_id")),
                    ("Document ID", source_document.get("xml_document_id") or source_document.get("document_id")),
                ]
            )
    return pdf.finish()


def lineage_pdf(report: dict[str, Any]) -> bytes:
    case_set = report.get("case_set") or {}
    selected = report.get("selected_cases") or []
    pdf = PDFReport("Lineage and execution trace", "Dataset, execution and selection provenance")
    pdf.title_block(
        "Lineage and execution trace",
        f"Case set {_plain(case_set.get('name'))} | generated {_format_when(report.get('generated_at'))}",
    )
    pdf.key_values(
        [
            ("Case-set ID", case_set.get("case_set_id")),
            ("External lot reference", case_set.get("external_lot_ref")),
            ("Final dataset", f"{_plain(case_set.get('dataset_id'))} v{_plain(case_set.get('dataset_version'))}"),
            ("Selection batch", case_set.get("selection_batch_id")),
            ("Evidence set", case_set.get("risk_result_set_name") or case_set.get("risk_result_set_id")),
        ]
    )
    pdf.section("Dataset ancestry")
    ancestry_rows = []
    for item in report.get("dataset_ancestry") or []:
        ancestry_rows.append(
            [
                item.get("sequence"),
                item.get("zone"),
                f"{_short(item.get('dataset_id'))} v{_plain(item.get('version'))}",
                item.get("transition") or "origin",
                _format_when(item.get("transition_at") or item.get("published_at") or item.get("created_at")),
            ]
        )
    pdf.table(
        ["Seq", "Zone", "Dataset", "Transition", "Created / published"],
        ancestry_rows,
        [32, 85, 145, 100, 153],
        font_size=6.8,
    )
    pdf.section("Publication events")
    promotions = report.get("promotions") or []
    if promotions:
        for event in promotions:
            pdf.key_values(
                [
                    ("Transition", f"{_plain(event.get('source_zone'))} -> {_plain(event.get('target_zone'))}"),
                    ("Promotion ID", event.get("promotion_id")),
                    ("Reason", event.get("reason")),
                    ("Gate run", event.get("gate_run_id")),
                    ("Eligible / rejected", f"{_plain(event.get('eligible_count'))} / {_plain(event.get('gate_rejected_count') or event.get('rejected_count'))}"),
                ]
            )
    else:
        pdf.paragraph("No promotion events were recorded.", color=MUTED)
    pdf.new_page()
    pdf.section("Function execution register")
    for run in report.get("runs") or []:
        pdf.paragraph(
            f"Run {_plain(run.get('run_id'))} | {_plain(run.get('purpose'))} | {_plain(run.get('status'))}",
            size=8,
            bold=True,
            after=4,
        )
        rows = []
        for child in run.get("function_runs") or []:
            rows.append(
                [
                    f"{_plain(child.get('stage'))} / {_plain(child.get('function_code'))} v{_plain(child.get('function_version'))}",
                    child.get("status"),
                    json.dumps(child.get("parameters") or {}, sort_keys=True, default=str),
                    json.dumps(child.get("result_summary") or {}, sort_keys=True, default=str),
                ]
            )
        if rows:
            pdf.table(
                ["Stage / function", "Status", "Parameters", "Result summary"],
                rows,
                [145, 70, 145, 155],
                font_size=6.2,
            )
    pdf.new_page()
    pdf.section("Selected cases carried into the final set")
    if selected:
        pdf.table(
            ["Case", "Entity / report", "Risk", "Decision", "Audit status"],
            _summary_rows(selected),
            [32, 190, 105, 85, 103],
        )
        for item in selected:
            pdf.key_values(
                [
                    ("Entity / report", f"{_plain(item.get('entity_name') or item.get('entity_id'))} / {_plain(item.get('report_id'))}"),
                    ("Audit case", item.get("audit_case_id")),
                    ("Decision rationale", item.get("decision_rationale")),
                    ("Source functions", ", ".join(item.get("source_functions") or []) or "-"),
                    ("Source run IDs", ", ".join(item.get("source_run_ids") or []) or "-"),
                ]
            )
    else:
        pdf.paragraph("No selected cases are associated with this case set.", color=MUTED)
    return pdf.finish()
