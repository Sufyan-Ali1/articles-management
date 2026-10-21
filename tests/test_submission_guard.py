import asyncio
from types import SimpleNamespace

import pytest

from app.core.errors import APIError
from app.services.requests import SubmissionGuard


async def test_guard_concurrent_and_expiration(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import requests

    clock = [100.0]
    monkeypatch.setattr(requests, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    guard = SubmissionGuard(max_keys=1)
    writes = []

    async def save() -> None:
        await asyncio.sleep(0)
        writes.append(True)

    await asyncio.gather(*(guard.submit("same", save) for _ in range(20)))
    assert len(writes) == 1
    with pytest.raises(APIError):
        await guard.submit("different", save)
    clock[0] += 601
    await guard.submit("same", save)
    assert len(writes) == 2


async def test_guard_releases_after_failed_save() -> None:
    guard = SubmissionGuard()

    async def fail() -> None:
        raise RuntimeError("Persistence failed")

    with pytest.raises(RuntimeError):
        await guard.submit("key", fail)
    saved = []

    async def save() -> None:
        saved.append(True)

    await guard.submit("key", save)
    assert saved == [True]


async def test_guard_owner_cancellation_allows_waiter_to_save() -> None:
    guard = SubmissionGuard()
    started = asyncio.Event()
    never = asyncio.Event()
    writes = []

    async def save() -> None:
        writes.append(True)
        if len(writes) == 1:
            started.set()
            await never.wait()

    owner = asyncio.create_task(guard.submit("key", save))
    await started.wait()
    waiter = asyncio.create_task(guard.submit("key", save))
    await asyncio.sleep(0)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    await asyncio.wait_for(waiter, timeout=1)
    assert len(writes) == 2
