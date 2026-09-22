from __future__ import annotations

import sys
from pathlib import Path

import pytest


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from cbcr_platform.access import AccessService
from cbcr_platform.bootstrap import seed
from cbcr_platform.canonical import SourceGateway
from cbcr_platform.config import get_settings
from cbcr_platform.database import Database
from cbcr_platform.runs import RunService


@pytest.fixture()
def services(tmp_path):
    db = Database(tmp_path / "control.db")
    db.initialise()
    seed(db)
    settings = get_settings(tmp_path / "control.db")
    access = AccessService(db)
    return db, access, RunService(db, SourceGateway(settings.fixture_root), access)
