import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import account_deletion


class _Client:
    calls: list = []

    def __init__(self, *_a, **_k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, url, data=None):
        _Client.calls.append(("post", url, data))
        return SimpleNamespace(status_code=200)

    async def delete(self, url, headers=None):
        _Client.calls.append(("delete", url, headers))
        return SimpleNamespace(status_code=204)


def test_revokes_strava_and_whoop():
    _Client.calls = []
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = SimpleNamespace(
        data=[{"provider": "strava", "access_token": "s"}, {"provider": "whoop", "access_token": "w"}]
    )
    with patch.object(account_deletion.httpx, "AsyncClient", _Client), patch.object(
        account_deletion, "decrypt_oauth_row", lambda r: r
    ):
        out = asyncio.run(account_deletion.revoke_provider_grants(db, "a1"))
    assert out == {"strava": True, "whoop": True}
    assert _Client.calls[0] == ("post", account_deletion.STRAVA_DEAUTHORIZE_URL, {"access_token": "s"})
    assert _Client.calls[1][0] == "delete" and _Client.calls[1][1].endswith("/user/access")


def test_token_read_failure_returns_empty():
    db = MagicMock()
    db.table.side_effect = RuntimeError("db down")
    assert asyncio.run(account_deletion.revoke_provider_grants(db, "a1")) == {}
