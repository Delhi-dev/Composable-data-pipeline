from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _integer(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class PostgreSQLSettings:
    host: str
    port: int
    database: str
    user: str
    password_env: str
    sslmode: str
    connect_timeout_seconds: int
    pool_min: int
    pool_max: int
    worker_poll_seconds: float
    worker_lease_seconds: int
    worker_max_attempts: int
    fixture_root: Path
    application_name: str = "cbcr-platform-postgresql"

    def password(self) -> str:
        value = os.getenv(self.password_env)
        if value is None:
            raise ValueError(
                f"required PostgreSQL secret environment variable is not set: {self.password_env}"
            )
        return value

    def redacted(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password_env": self.password_env,
            "sslmode": self.sslmode,
            "pool_min": self.pool_min,
            "pool_max": self.pool_max,
        }


def get_settings() -> PostgreSQLSettings:
    password_env = os.getenv("CBCR_PG_PASSWORD_ENV", "CBCR_SOURCE_DB_PASSWORD")
    pool_min = _integer("CBCR_PG_POOL_MIN", 1)
    pool_max = _integer("CBCR_PG_POOL_MAX", 8)
    if pool_max < pool_min:
        raise ValueError("CBCR_PG_POOL_MAX must be greater than or equal to CBCR_PG_POOL_MIN")
    sslmode = os.getenv("CBCR_PG_SSLMODE", "prefer")
    if sslmode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
        raise ValueError("CBCR_PG_SSLMODE is invalid")
    return PostgreSQLSettings(
        host=os.getenv("CBCR_PG_HOST", "localhost"),
        port=_integer("CBCR_PG_PORT", 5432),
        database=os.getenv("CBCR_PG_DATABASE", "cbcr"),
        user=os.getenv("CBCR_PG_USER", "cbcr_user"),
        password_env=password_env,
        sslmode=sslmode,
        connect_timeout_seconds=_integer("CBCR_PG_CONNECT_TIMEOUT_SECONDS", 5),
        pool_min=pool_min,
        pool_max=pool_max,
        worker_poll_seconds=_float("CBCR_WORKER_POLL_SECONDS", 0.2),
        worker_lease_seconds=_integer("CBCR_WORKER_LEASE_SECONDS", 60),
        worker_max_attempts=_integer("CBCR_WORKER_MAX_ATTEMPTS", 3),
        fixture_root=PACKAGE_ROOT / "fixtures",
    )

