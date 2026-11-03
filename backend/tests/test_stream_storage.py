"""Tests for gzip JSON stream storage helpers."""
from __future__ import annotations

import gzip
import json
from unittest.mock import MagicMock, patch

from app.services import stream_storage


def test_streams_dict_to_time_series():
    streams = {
        "heartrate": {"data": [120, 121]},
        "time": {"data": [0, 1]},
    }
    ts = stream_storage.streams_dict_to_time_series(streams)
    assert ts["heartrate"] == [120, 121]
    assert ts["time"] == [0, 1]


def test_time_series_roundtrip_shape():
    ts = {"heartrate": [100, 101], "velocity_smooth": [1.0, 2.0]}
    rebuilt = stream_storage.time_series_to_streams_dict(ts)
    assert rebuilt["heartrate"]["data"] == [100, 101]


def test_resolve_time_series_prefers_storage():
    stored = {"heartrate": [1, 2, 3]}
    body = gzip.compress(json.dumps(stored).encode())
    with patch.object(stream_storage, "download_time_series_gzip", return_value=stored):
        row = {"athlete_id": "a", "workout_id": "w", "storage_path": "a/w.json.gz", "time_series": {"heartrate": [9]}}
        assert stream_storage.resolve_time_series(row) == stored


def test_resolve_time_series_ignores_foreign_storage_path():
    """A user-edited storage_path pointing at another athlete's blob is never downloaded."""
    with patch.object(stream_storage, "download_time_series_gzip") as dl:
        row = {"athlete_id": "me", "workout_id": "w1", "storage_path": "victim/w9.json.gz", "time_series": None}
        assert stream_storage.resolve_time_series(row) is None
    dl.assert_not_called()


def test_gunzip_bounded_rejects_bombs():
    import pytest

    bomb = gzip.compress(b"0" * (2 * 1024 * 1024))
    with pytest.raises(ValueError):
        stream_storage._gunzip_bounded(bomb, limit=1024 * 1024)
    assert stream_storage._gunzip_bounded(gzip.compress(b"{}"), limit=1024) == b"{}"


def test_resolve_time_series_legacy_jsonb():
    legacy = {"heartrate": [5, 6]}
    row = {"time_series": legacy}
    assert stream_storage.resolve_time_series(row) == legacy


@patch("app.services.stream_storage.get_admin_db")
def test_upload_time_series_gzip(mock_admin):
    client = MagicMock()
    mock_admin.return_value = client
    ts = {"time": [0, 1]}
    path, size = stream_storage.upload_time_series_gzip("athlete-1", "workout-1", ts)
    assert path == "athlete-1/workout-1.json.gz"
    assert size > 0
    client.storage.from_.assert_called_with("activity-streams")
    upload = client.storage.from_.return_value.upload
    upload.assert_called_once()
    args, kwargs = upload.call_args
    assert args[0] == path
    assert isinstance(args[1], bytes)
    assert kwargs["file_options"]["upsert"] == "true"
