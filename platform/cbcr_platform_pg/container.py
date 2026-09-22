from __future__ import annotations

from cbcr_platform.canonical import SourceGateway

from .access import AccessService
from .admin import AdminService
from .bootstrap import seed
from .catalog import CatalogueService
from .config import get_settings
from .data_plane import DataPlaneService
from .database import PostgreSQLDatabase
from .runs import RunService
from .worker import PostgreSQLRunWorker


class PostgreSQLContainer:
    def __init__(self):
        self.settings = get_settings()
        self.db = PostgreSQLDatabase(self.settings)
        self.db.verify_migrations()
        seed(self.db)
        self.access = AccessService(self.db)
        self.catalogue = CatalogueService(self.db)
        self.admin = AdminService(self.db)
        self.gateway = SourceGateway(self.settings.fixture_root)
        self.data_plane = DataPlaneService(self.db, self.gateway)
        self.runs = RunService(
            self.db,
            self.access,
            self.data_plane,
            maximum_attempts=self.settings.worker_max_attempts,
            lease_seconds=self.settings.worker_lease_seconds,
        )
        self.worker = PostgreSQLRunWorker(
            self.runs, poll_seconds=self.settings.worker_poll_seconds
        )

    def close(self) -> None:
        self.db.close()

