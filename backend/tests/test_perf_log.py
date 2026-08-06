import logging

from app.core.perf_log import payload_bytes, perf_span


def test_payload_bytes_measures_json_encoded_size():
    data = {"a": 1, "b": "two"}
    expected = len(__import__("json").dumps(data, default=str).encode("utf-8"))

    assert payload_bytes(data) == expected


def test_payload_bytes_returns_zero_for_unserializable_data():
    # json.dumps(default=str) falls back to str(obj); make that fail too so the
    # dumps call itself raises and payload_bytes hits its except-Exception path.
    class Evil:
        def __str__(self):
            raise TypeError("nope")

    assert payload_bytes(Evil()) == 0


def test_perf_span_logs_duration_and_extra_fields(caplog):
    with caplog.at_level(logging.INFO):
        with perf_span("my-op", athlete_id="athlete-1") as extra:
            extra["rows"] = 5

    messages = [record.getMessage() for record in caplog.records]
    logged = next(m for m in messages if "[perf] my-op" in m)
    assert "duration_ms" in logged
    assert "rows" in logged


def test_perf_span_logs_even_when_block_raises(caplog):
    with caplog.at_level(logging.INFO):
        try:
            with perf_span("failing-op"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

    messages = [record.getMessage() for record in caplog.records]
    assert any("[perf] failing-op" in m for m in messages)
