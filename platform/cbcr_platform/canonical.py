from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .contracts import CanonicalEntity, CanonicalMetric, CanonicalReport


class MappingError(ValueError):
    pass


def _path(value: Any, dotted: str) -> Any:
    current = value
    if dotted in ("", "."):
        return current
    for part in dotted.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _map_fields(record: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {canonical: _path(record, physical) for canonical, physical in mapping.items()}


class FixtureSourceAdapter:
    def __init__(self, fixture_root: Path):
        self.fixture_root = fixture_root.resolve()

    def records(self, endpoint_link: str) -> list[dict[str, Any]]:
        path = (self.fixture_root / endpoint_link).resolve()
        if self.fixture_root not in path.parents:
            raise ValueError("fixture endpoint must remain inside the fixture root")
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records", payload) if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise ValueError("fixture source must contain a record list")
        return records


class PostgreSQLCanonicalAdapter:
    """Reads the stable JSON view; physical XML table names never escape this boundary."""

    _IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")

    @staticmethod
    def _password(secret_ref: str | None) -> str:
        if not secret_ref or not secret_ref.startswith("env:"):
            raise ValueError("PostgreSQL sources require an env:NAME secret reference")
        variable = secret_ref.removeprefix("env:")
        password = os.environ.get(variable)
        if password is None:
            raise ValueError(f"required database secret environment variable is not set: {variable}")
        return password

    def records(self, endpoint_link: str, secret_ref: str | None) -> list[dict[str, Any]]:
        endpoint = urlparse(endpoint_link)
        if endpoint.scheme not in {"postgres", "postgresql"}:
            raise ValueError("PostgreSQL endpoint must use postgres:// or postgresql://")
        if endpoint.password:
            raise ValueError("database passwords must use secret_ref and must not be embedded in endpoint_link")
        if not endpoint.hostname or not endpoint.username or not endpoint.path.strip("/"):
            raise ValueError("PostgreSQL endpoint requires user, host, and database")
        options = parse_qs(endpoint.query, keep_blank_values=False)
        unknown = set(options) - {"view", "sslmode", "connect_timeout"}
        if unknown:
            raise ValueError(f"unsupported PostgreSQL endpoint options: {', '.join(sorted(unknown))}")
        view = options.get("view", [endpoint.fragment])[0]
        if not view or not self._IDENTIFIER.fullmatch(view):
            raise ValueError("PostgreSQL endpoint requires a schema-qualified, identifier-safe view")
        timeout = int(options.get("connect_timeout", ["5"])[0])

        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError("PostgreSQL adapter requires psycopg2") from exc

        connection = psycopg2.connect(
            host=endpoint.hostname,
            port=endpoint.port or 5432,
            dbname=endpoint.path.strip("/"),
            user=unquote(endpoint.username),
            password=self._password(secret_ref),
            sslmode=options.get("sslmode", ["prefer"])[0],
            connect_timeout=timeout,
            application_name="cbcr-pipeline-scaffold",
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT report_payload FROM {view} ORDER BY report_id")
                payloads = [row[0] for row in cursor.fetchall()]
        finally:
            connection.close()
        records = [json.loads(value) if isinstance(value, str) else value for value in payloads]
        if not all(isinstance(value, dict) for value in records):
            raise ValueError("canonical PostgreSQL view must return JSON objects in report_payload")
        return records


class SourceGateway:
    """Physical source access. Live DB details terminate here, never in functions."""

    def __init__(self, fixture_root: Path):
        self.fixture = FixtureSourceAdapter(fixture_root)
        self.postgresql = PostgreSQLCanonicalAdapter()

    def records(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        if source["adapter_type"] == "fixture-json":
            return self.fixture.records(source["endpoint_link"])
        if source["adapter_type"] == "postgresql-canonical":
            return self.postgresql.records(source["endpoint_link"], source.get("secret_ref"))
        raise NotImplementedError(
            f"source adapter is not implemented: {source['adapter_type']}"
        )


class CanonicalMapper:
    def __init__(self, mapping: dict[str, Any]):
        self.mapping = deepcopy(mapping)

    def source_record_id(self, raw: dict[str, Any]) -> str:
        value = _path(raw, self.mapping["report"]["report_id"])
        if value is None:
            raise MappingError("mapped report_id is missing")
        return str(value)

    def map_report(self, raw: dict[str, Any]) -> CanonicalReport:
        report = _map_fields(raw, self.mapping["report"])
        entity_spec = self.mapping["entities"]
        metric_spec = self.mapping["metrics"]
        entity_rows = _path(raw, entity_spec["path"]) or []
        metric_rows = _path(raw, metric_spec["path"]) or []
        report["entities"] = [CanonicalEntity(**_map_fields(row, entity_spec["fields"])) for row in entity_rows]
        report["metrics"] = [CanonicalMetric(**_map_fields(row, metric_spec["fields"])) for row in metric_rows]
        try:
            return CanonicalReport(**report)
        except Exception as exc:
            raise MappingError(f"record does not satisfy canonical contract: {exc}") from exc


def snapshot_hash(raw: dict[str, Any]) -> str:
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class CanonicalDataAPI:
    """The only data surface exposed to quality and risk functions."""

    def __init__(self, reports: list[CanonicalReport]):
        self._reports = {report.report_id: report for report in reports}

    def list_reports(self) -> list[CanonicalReport]:
        return list(self._reports.values())

    def get_report(self, report_id: str) -> CanonicalReport | None:
        return self._reports.get(report_id)

    def list_entities(self, report_id: str | None = None) -> list[CanonicalEntity]:
        if report_id is not None and report_id not in self._reports:
            return []
        reports = [self._reports[report_id]] if report_id is not None else self.list_reports()
        return [entity for report in reports for entity in report.entities]

    def get_jurisdiction_metrics(
        self, report_id: str, jurisdiction: str | None = None,
    ) -> list[CanonicalMetric]:
        report = self._reports.get(report_id)
        if not report:
            return []
        return [
            metric for metric in report.metrics
            if jurisdiction is None or metric.jurisdiction == jurisdiction.upper()
        ]

    def aggregate_metrics(self, report_id: str) -> dict[str, float]:
        metrics = self.get_jurisdiction_metrics(report_id)
        names = ("revenue", "profit_before_tax", "income_tax_paid", "employees")
        return {
            name: float(sum((getattr(metric, name) or 0) for metric in metrics))
            for name in names
        }

    def resolve_lineage(self, report_id: str) -> dict[str, str] | None:
        report = self.get_report(report_id)
        return None if not report else {
            "report_id": report.report_id, "message_ref_id": report.message_ref_id
        }
