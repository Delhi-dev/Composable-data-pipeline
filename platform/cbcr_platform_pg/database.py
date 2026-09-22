from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

import psycopg2
from psycopg2 import errors
from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from .config import PostgreSQLSettings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


def _adapt(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return Json(value)
    return value


def _params(values: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(_adapt(value) for value in values)


class PostgreSQLSession:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(sql, _params(params)) if params else cursor.execute(sql)
            return cursor.rowcount

    def execute_many(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        with self.connection.cursor() as cursor:
            cursor.executemany(sql, [_params(row) for row in rows])

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql, _params(params)) if params else cursor.execute(sql)
            row = cursor.fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql, _params(params)) if params else cursor.execute(sql)
            return [dict(row) for row in cursor.fetchall()]


class PostgreSQLDatabase:
    required_migration = "009_xml_ingestion_runtime"

    def __init__(self, settings: PostgreSQLSettings):
        self.settings = settings
        self.pool = ThreadedConnectionPool(
            settings.pool_min,
            settings.pool_max,
            host=settings.host,
            port=settings.port,
            dbname=settings.database,
            user=settings.user,
            password=settings.password(),
            sslmode=settings.sslmode,
            connect_timeout=settings.connect_timeout_seconds,
            application_name=settings.application_name,
        )

    @contextmanager
    def transaction(self) -> Iterator[PostgreSQLSession]:
        connection = self.pool.getconn()
        connection.autocommit = False
        try:
            yield PostgreSQLSession(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self.pool.putconn(connection)

    @contextmanager
    def read(self) -> Iterator[PostgreSQLSession]:
        connection = self.pool.getconn()
        connection.autocommit = False
        try:
            yield PostgreSQLSession(connection)
            connection.rollback()
        finally:
            self.pool.putconn(connection)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.transaction() as session:
            return session.execute(sql, params)

    def execute_many(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        with self.transaction() as session:
            session.execute_many(sql, rows)

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.read() as session:
            return session.one(sql, params)

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.read() as session:
            return session.all(sql, params)

    def ping(self) -> dict[str, Any]:
        row = self.one(
            "SELECT current_database() AS database,current_user AS username,"
            "current_setting('server_version') AS server_version"
        )
        return row or {}

    def verify_migrations(self) -> None:
        row = self.one(
            "SELECT migration_id FROM cbcr_control.schema_migration WHERE migration_id=%s",
            (self.required_migration,),
        )
        if not row:
            raise RuntimeError(
                f"required PostgreSQL migration is not applied: {self.required_migration}"
            )

    def audit(
        self,
        event_id: str,
        actor: str,
        action: str,
        resource: str,
        decision: str,
        purpose: str | None = None,
        detail: dict[str, Any] | None = None,
        session: PostgreSQLSession | None = None,
    ) -> None:
        sql = """INSERT INTO cbcr_control.audit_event
            (event_id,actor,action,resource,purpose,decision,detail,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)"""
        values = (event_id, actor, action, resource, purpose, decision, detail or {}, utc_now())
        if session:
            session.execute(sql, values)
        else:
            self.execute(sql, values)

    def close(self) -> None:
        self.pool.closeall()


__all__ = [
    "PostgreSQLDatabase",
    "PostgreSQLSession",
    "errors",
    "new_uuid",
    "utc_now",
]
