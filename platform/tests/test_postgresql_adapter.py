from __future__ import annotations

from pathlib import Path

import pytest

from cbcr_platform.canonical import PostgreSQLCanonicalAdapter, SourceGateway


def test_postgresql_source_requires_environment_secret(monkeypatch):
    monkeypatch.delenv("UNSET_CBCR_TEST_PASSWORD", raising=False)
    gateway = SourceGateway(Path("."))
    with pytest.raises(ValueError, match="environment variable is not set"):
        gateway.records({
            "adapter_type": "postgresql-canonical",
            "endpoint_link": (
                "postgresql://cbcr_user@localhost:5432/cbcr"
                "?view=cbcr_canonical.v_api_report_json"
            ),
            "secret_ref": "env:UNSET_CBCR_TEST_PASSWORD",
        })


def test_postgresql_source_rejects_passwords_and_unsafe_view_names(monkeypatch):
    adapter = PostgreSQLCanonicalAdapter()
    monkeypatch.setenv("CBCR_TEST_PASSWORD", "not-a-real-secret")
    with pytest.raises(ValueError, match="must not be embedded"):
        adapter.records(
            "postgresql://user:password@localhost/db?view=cbcr_canonical.v_api_report_json",
            "env:CBCR_TEST_PASSWORD",
        )
    with pytest.raises(ValueError, match="identifier-safe"):
        adapter.records(
            "postgresql://user@localhost/db?view=cbcr_canonical.v_api_report_json%3BDELETE",
            "env:CBCR_TEST_PASSWORD",
        )
