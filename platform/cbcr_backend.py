"""Deployment-time selector for the SQLite or PostgreSQL control plane.

Use ``CBCR_PERSISTENCE_BACKEND=postgresql`` to select the PostgreSQL package.
The default deliberately remains SQLite so existing launch commands keep working.
"""
from __future__ import annotations

import os


backend = os.getenv("CBCR_PERSISTENCE_BACKEND", "sqlite").strip().lower()
if backend in {"postgres", "postgresql", "pg"}:
    from cbcr_platform_pg.api import app
elif backend == "sqlite":
    from cbcr_platform.api import app
else:
    raise RuntimeError(
        "CBCR_PERSISTENCE_BACKEND must be sqlite or postgresql "
        f"(received {backend!r})"
    )


__all__ = ["app"]
