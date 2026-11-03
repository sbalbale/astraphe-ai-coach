import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import whoop


class _Client:
    def __init__(self, responses):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, *_a, **_k):
        return self._responses.pop(0)


def _res(status, payload=None, headers=None):
    return SimpleNamespace(status_code=status, json=lambda: payload or {}, headers=headers or {}, text="")


def test_fetch_collection_retries_429_then_continues():
    responses = [
        _res(200, {"records": [{"id": 1}], "next_token": "t2"}),
        _res(429, headers={"Retry-After": "2"}),
        _res(200, {"records": [{"id": 2}]}),
    ]
    sleep = AsyncMock()
    with patch.object(whoop.httpx, "AsyncClient", lambda *a, **k: _Client(responses)), patch.object(
        whoop.asyncio, "sleep", sleep
    ):
        records = asyncio.run(whoop.fetch_collection("tok", "recovery"))
    assert [r["id"] for r in records] == [1, 2]
    sleep.assert_awaited_once_with(2.0)
