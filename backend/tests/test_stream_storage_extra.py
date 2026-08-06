from __future__ import annotations

import gzip
import json
from unittest.mock import MagicMock, patch

from app.services import stream_storage


def test_streams_dict_to_time_series_skips_non_dict_and_non_list_values():
    streams = {"heartrate": {"data": [1, 2]}, "junk": "not-a-dict", "empty": {"data": "not-a-list"}}
    out = stream_storage.streams_dict_to_time_series(streams)
    assert out == {"heartrate": [1, 2]}


def test_time_series_to_streams_dict_empty_or_non_dict_returns_empty():
    assert stream_storage.time_series_to_streams_dict(None) == {}
    assert stream_storage.time_series_to_streams_dict({}) == {}
    assert stream_storage.time_series_to_streams_dict("not-a-dict") == {}


def test_time_series_to_streams_dict_passes_through_already_wrapped_values():
    ts = {"heartrate": {"data": [1, 2]}, "bad": {"nope": True}, "worse": 42}
    out = stream_storage.time_series_to_streams_dict(ts)
    assert out == {"heartrate": {"data": [1, 2]}}


def test_download_time_series_gzip_returns_none_for_blank_path():
    assert stream_storage.download_time_series_gzip("") is None


def test_download_time_series_gzip_returns_none_on_download_error():
    fake_client = MagicMock()
    fake_client.storage.from_.return_value.download.side_effect = RuntimeError("not found")
    with patch.object(stream_storage, "get_admin_db", return_value=fake_client):
        assert stream_storage.download_time_series_gzip("a/w.json.gz") is None


def test_download_time_series_gzip_returns_none_for_empty_response():
    fake_client = MagicMock()
    fake_client.storage.from_.return_value.download.return_value = None
    with patch.object(stream_storage, "get_admin_db", return_value=fake_client):
        assert stream_storage.download_time_series_gzip("a/w.json.gz") is None


def test_download_time_series_gzip_returns_none_on_corrupt_payload():
    fake_client = MagicMock()
    fake_client.storage.from_.return_value.download.return_value = b"not-gzip-data"
    with patch.object(stream_storage, "get_admin_db", return_value=fake_client):
        assert stream_storage.download_time_series_gzip("a/w.json.gz") is None


def test_download_time_series_gzip_returns_none_for_non_dict_json():
    body = gzip.compress(json.dumps([1, 2, 3]).encode())
    fake_client = MagicMock()
    fake_client.storage.from_.return_value.download.return_value = body
    with patch.object(stream_storage, "get_admin_db", return_value=fake_client):
        assert stream_storage.download_time_series_gzip("a/w.json.gz") is None


def test_download_time_series_gzip_parses_valid_payload():
    body = gzip.compress(json.dumps({"heartrate": [1, 2]}).encode())
    fake_client = MagicMock()
    fake_client.storage.from_.return_value.download.return_value = body
    with patch.object(stream_storage, "get_admin_db", return_value=fake_client):
        assert stream_storage.download_time_series_gzip("a/w.json.gz") == {"heartrate": [1, 2]}


def test_resolve_time_series_returns_none_for_empty_row():
    assert stream_storage.resolve_time_series(None) is None
    assert stream_storage.resolve_time_series({}) is None


def test_resolve_time_series_falls_back_to_legacy_when_storage_empty():
    with patch.object(stream_storage, "download_time_series_gzip", return_value=None):
        row = {"storage_path": "a/w.json.gz", "time_series": {"heartrate": [1]}}
        assert stream_storage.resolve_time_series(row) == {"heartrate": [1]}


def test_resolve_time_series_none_when_no_storage_and_bad_legacy():
    assert stream_storage.resolve_time_series({"time_series": "not-a-dict"}) is None
    assert stream_storage.resolve_time_series({"time_series": {}}) is None


def test_fetch_stream_row_columns_returns_none_when_missing():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data=None
    )
    assert stream_storage.fetch_stream_row_columns(db, "workout-1", "athlete-1") is None


def test_fetch_stream_row_columns_handles_list_shaped_data():
    row = {"time_series": {"heartrate": [1, 2]}, "resolution_seconds": 5, "created_at": "t"}
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data=[row]
    )
    result = stream_storage.fetch_stream_row_columns(db, "workout-1", "athlete-1")
    assert result["resolution_seconds"] == 5


def test_fetch_stream_row_columns_returns_none_for_empty_list():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data=[]
    )
    assert stream_storage.fetch_stream_row_columns(db, "workout-1", "athlete-1") is None


def test_fetch_stream_row_columns_returns_none_for_non_dict_data():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data="unexpected-shape"
    )
    assert stream_storage.fetch_stream_row_columns(db, "workout-1", "athlete-1") is None


def test_fetch_stream_row_columns_returns_empty_series_when_storage_blob_missing():
    row = {"storage_path": "a/w.json.gz", "time_series": None, "resolution_seconds": None}
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data=row
    )
    with patch.object(stream_storage, "download_time_series_gzip", return_value=None):
        result = stream_storage.fetch_stream_row_columns(db, "workout-1", "athlete-1")

    assert result["time_series"] == {}
    assert result["resolution_seconds"] == 1


def test_fetch_stream_row_columns_returns_none_when_no_storage_and_no_legacy():
    row = {"storage_path": None, "time_series": None}
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data=row
    )
    assert stream_storage.fetch_stream_row_columns(db, "workout-1", "athlete-1") is None
