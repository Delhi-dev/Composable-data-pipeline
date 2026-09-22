from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_path: Path
    fixture_root: Path
    worker_poll_seconds: float = 0.2


def get_settings(database_path: str | Path | None = None) -> Settings:
    configured = database_path or os.getenv("CBCR_CONTROL_DB")
    db_path = Path(configured) if configured else PACKAGE_ROOT / "runtime" / "control-plane.db"
    return Settings(database_path=db_path, fixture_root=PACKAGE_ROOT / "fixtures")
