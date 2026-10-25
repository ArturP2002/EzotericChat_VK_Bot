"""Блокировка на пользователя, чтобы два сообщения подряд не путали списание кредитов."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

_locks: dict[int, asyncio.Lock] = {}
_meta = asyncio.Lock()


@asynccontextmanager
async def user_lock(vk_id: int) -> AsyncIterator[None]:
    async with _meta:
        lock = _locks.setdefault(vk_id, asyncio.Lock())
    async with lock:
        yield
