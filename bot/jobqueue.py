"""Cola justa para las operaciones con el CLI (las que gastan CPU y red del servidor).

Hasta `limit()` trabajos a la vez; el resto espera en orden de llegada y se le avisa de su posición
(y de cada cambio de posición) con la función `on_pos(n)` que pase. `on_pos(0)` = empieza ya.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Awaitable, Callable

log = logging.getLogger(__name__)
OnPos = Callable[[int], Awaitable[None]]


class FairQueue:
    def __init__(self, limit: Callable[[], int]):
        self.limit = limit
        self.active = 0
        self.waiting: list[tuple[asyncio.Future, OnPos | None]] = []

    def position(self) -> int:
        """Cuántos esperan ahora (0 = hay sitio libre)."""
        return len(self.waiting) if self.active >= max(1, self.limit()) or self.waiting else 0

    async def _tell(self, cb: OnPos | None, n: int) -> None:
        if cb:
            try:
                await cb(n)
            except Exception as e:  # noqa: BLE001
                log.info("aviso de cola: %s", e)

    async def acquire(self, on_pos: OnPos | None = None) -> None:
        if self.active < max(1, self.limit()) and not self.waiting:
            self.active += 1
            return
        fut = asyncio.get_running_loop().create_future()
        self.waiting.append((fut, on_pos))
        await self._tell(on_pos, len(self.waiting))
        try:
            await fut
        except asyncio.CancelledError:
            if (fut, on_pos) in self.waiting:
                self.waiting.remove((fut, on_pos))
                self._renumber()
            elif fut.done() and not fut.cancelled():
                self.release()      # ya le tocaba: pasa el turno
            raise
        await self._tell(on_pos, 0)

    def release(self) -> None:
        self.active = max(0, self.active - 1)
        while self.waiting and self.active < max(1, self.limit()):
            fut, _ = self.waiting.pop(0)
            if fut.done():
                continue
            self.active += 1
            fut.set_result(True)
        self._renumber()

    def _renumber(self) -> None:
        for i, (_, cb) in enumerate(self.waiting, 1):
            if cb:
                asyncio.ensure_future(self._tell(cb, i))

    @contextlib.asynccontextmanager
    async def slot(self, on_pos: OnPos | None = None):
        await self.acquire(on_pos)
        try:
            yield
        finally:
            self.release()
