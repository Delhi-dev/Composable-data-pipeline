from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import pytest
from fastapi.testclient import TestClient


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))


@pytest.fixture(scope="session")
def pg_runtime():
    secret_name = os.getenv("CBCR_PG_PASSWORD_ENV", "CBCR_SOURCE_DB_PASSWORD")
    if not os.getenv(secret_name):
        pytest.skip(f"PostgreSQL acceptance requires the {secret_name} test secret")
    from cbcr_platform_pg.api import app, container

    # Deliberately omit TestClient's lifespan: tests drain the durable queue with
    # two explicit workers, making worker ownership deterministic and observable.
    client = TestClient(app)
    yield client, container
    container.close()


@pytest.fixture(scope="session")
def drain_queue(pg_runtime):
    _, container = pg_runtime

    def drain() -> list[tuple[str, str]]:
        claimed: list[tuple[str, str]] = []
        lock = Lock()

        def worker(worker_id: str) -> None:
            while True:
                value = container.runs.claim_next(worker_id)
                if not value:
                    return
                with lock:
                    claimed.append((str(value["function_run_id"]), worker_id))
                container.runs.process_claimed(value)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, f"acceptance-worker-{index}") for index in (1, 2)]
            for future in futures:
                future.result()
        return claimed

    return drain
