from __future__ import annotations

import sys
from pathlib import Path


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from tools import railway_bootstrap


def test_fresh_bootstrap_runs_complete_migration_sequence(monkeypatch):
    captured = []
    monkeypatch.setattr(railway_bootstrap.subprocess, "run", lambda command, check: captured.append(command))

    railway_bootstrap.apply_migrations(established=False)

    assert len(captured) == 1
    assert "--from" not in captured[0]
    assert "--through" not in captured[0]


def test_established_bootstrap_runs_only_v2_migration(monkeypatch):
    captured = []
    monkeypatch.setattr(railway_bootstrap.subprocess, "run", lambda command, check: captured.append(command))

    railway_bootstrap.apply_migrations(established=True)

    assert len(captured) == 1
    assert captured[0][-4:] == ["--from", "011", "--through", "011"]
