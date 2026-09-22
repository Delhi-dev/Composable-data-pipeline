from __future__ import annotations

import asyncio
import socket
import uuid

from .runs import RunService


class PostgreSQLRunWorker:
    def __init__(
        self,
        service: RunService,
        poll_seconds: float = 0.2,
        worker_id: str | None = None,
    ):
        self.service = service
        self.poll_seconds = poll_seconds
        self.worker_id = worker_id or f"{socket.gethostname()}:{uuid.uuid4()}"
        self._stop = asyncio.Event()

    async def run(self) -> None:
        self.service.recover_expired()
        while not self._stop.is_set():
            claimed = await asyncio.to_thread(self.service.claim_next, self.worker_id)
            if claimed:
                await asyncio.to_thread(self.service.process_claimed, claimed)
                continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                self.service.recover_expired()

    def stop(self) -> None:
        self._stop.set()
