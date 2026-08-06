from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import settings
from app.services import memory


def test_get_embedding_model_name_adds_models_prefix(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
    assert memory._get_embedding_model_name() == "models/gemini-embedding-2"


def test_get_embedding_model_name_keeps_existing_prefix(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-2")
    assert memory._get_embedding_model_name() == "models/gemini-embedding-2"


def test_extract_embedding_from_dict_embedding():
    resp = SimpleNamespace(embedding={"values": [0.1, 0.2]})
    with patch.object(memory._client.models, "embed_content", return_value=resp):
        assert memory._extract_embedding("text") == [0.1, 0.2]


def test_extract_embedding_from_list_of_objects():
    resp = SimpleNamespace(embedding=[SimpleNamespace(values=[0.3, 0.4])])
    with patch.object(memory._client.models, "embed_content", return_value=resp):
        assert memory._extract_embedding("text") == [0.3, 0.4]


def test_extract_embedding_from_embeddings_attr_when_embedding_missing():
    resp = SimpleNamespace(embedding=None, embeddings={"vector": [0.5]})
    with patch.object(memory._client.models, "embed_content", return_value=resp):
        assert memory._extract_embedding("text") == [0.5]


def test_extract_embedding_returns_empty_when_nothing_found():
    resp = SimpleNamespace(embedding=None, embeddings=None)
    with patch.object(memory._client.models, "embed_content", return_value=resp):
        assert memory._extract_embedding("text") == []


class _MemQuery:
    def __init__(self, existing_rows=None, insert_error=None):
        self._existing_rows = existing_rows or []
        self._insert_error = insert_error
        self.inserted_payloads: list[dict] = []
        self._raise_once = insert_error is not None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.inserted_payloads.append(payload)
        if self._raise_once:
            self._raise_once = False
            raise self._insert_error
        return self

    def execute(self):
        return SimpleNamespace(data=self._existing_rows)


class _MemDb:
    def __init__(self, query):
        self._query = query

    def table(self, name):
        assert name == "coach_memories"
        return self._query


def test_save_coach_memory_noop_for_blank_content():
    db = _MemDb(_MemQuery())
    memory.save_coach_memory("athlete-1", "   ", db)
    assert db._query.inserted_payloads == []


def test_save_coach_memory_skips_when_duplicate_exists():
    db = _MemDb(_MemQuery(existing_rows=[{"id": "dup-1"}]))
    with patch.object(memory, "_extract_embedding", return_value=[]):
        memory.save_coach_memory("athlete-1", "New fact", db)
    assert db._query.inserted_payloads == []


def test_save_coach_memory_inserts_new_fact():
    db = _MemDb(_MemQuery())
    with patch.object(memory, "_extract_embedding", return_value=[0.1]):
        memory.save_coach_memory("athlete-1", "New fact", db)
    assert len(db._query.inserted_payloads) == 1
    assert db._query.inserted_payloads[0]["content"] == "New fact"


def test_save_coach_memory_retries_without_structured_columns_on_schema_drift():
    db = _MemDb(_MemQuery(insert_error=RuntimeError("PGRST204: schema mismatch")))
    with patch.object(memory, "_extract_embedding", return_value=[0.1]):
        memory.save_coach_memory("athlete-1", "New fact", db)

    assert len(db._query.inserted_payloads) == 2
    assert "memory_type" not in db._query.inserted_payloads[1]
    assert "updated_at" not in db._query.inserted_payloads[1]


def test_save_coach_memory_swallows_unexpected_insert_error(capsys):
    db = _MemDb(_MemQuery(insert_error=RuntimeError("totally unrelated failure")))
    with patch.object(memory, "_extract_embedding", return_value=[0.1]):
        memory.save_coach_memory("athlete-1", "New fact", db)  # should not raise

    assert "save failed" in capsys.readouterr().out


def test_normalize_entity_key_strips_punctuation_and_lowercases():
    assert memory._normalize_entity_key("  Boston Marathon! ") == "boston marathon"


def test_upsert_race_memory_requires_name():
    result = memory.upsert_race_memory(
        "athlete-1", race_name="  ", event_date=date(2026, 6, 28), db=MagicMock()
    )
    assert result == {"error": "race_name is required"}


def test_upsert_race_memory_requires_valid_date():
    result = memory.upsert_race_memory(
        "athlete-1", race_name="Boston Marathon", event_date="not-a-date", db=MagicMock()
    )
    assert result == {"error": "event_date must be a date"}


def test_upsert_race_memory_updates_existing_row():
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "mem-1", "content": "old", "event_date": "2026-05-28", "entity_key": "boston marathon"}]
    )
    fake_db.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "mem-1"}]
    )

    with patch.object(memory, "_extract_embedding", return_value=[0.1]):
        result = memory.upsert_race_memory(
            "athlete-1",
            race_name="Boston Marathon",
            event_date=date(2026, 6, 28),
            goal="sub 3:00",
            notes="taper starting",
            db=fake_db,
        )

    assert result["status"] == "updated"
    assert result["id"] == "mem-1"
    assert "Goal: sub 3:00" in result["content"]


def test_upsert_race_memory_inserts_new_row_when_none_exists():
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[]
    )
    fake_db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "mem-2"}]
    )

    with patch.object(memory, "_extract_embedding", return_value=[0.1]):
        result = memory.upsert_race_memory(
            "athlete-1", race_name="Boston Marathon", event_date=date(2026, 6, 28), db=fake_db
        )

    assert result["status"] == "inserted"
    assert result["id"] == "mem-2"


def test_upsert_race_memory_returns_error_on_exception():
    fake_db = MagicMock()
    fake_db.table.side_effect = RuntimeError("db down")

    with patch.object(memory, "_extract_embedding", return_value=[]):
        result = memory.upsert_race_memory(
            "athlete-1", race_name="Boston Marathon", event_date=date(2026, 6, 28), db=fake_db
        )

    assert "error" in result


def test_list_coach_memories_returns_rows():
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "1"}]
    )

    result = memory.list_coach_memories("athlete-1", db=fake_db)
    assert result == [{"id": "1"}]


def test_list_coach_memories_filters_by_type():
    fake_db = MagicMock()
    chain = fake_db.table.return_value.select.return_value.eq.return_value
    chain.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"id": "1", "memory_type": "race"}]
    )

    result = memory.list_coach_memories("athlete-1", db=fake_db, memory_type="race")
    assert result == [{"id": "1", "memory_type": "race"}]


def test_list_coach_memories_returns_empty_on_exception():
    fake_db = MagicMock()
    fake_db.table.side_effect = RuntimeError("db down")

    assert memory.list_coach_memories("athlete-1", db=fake_db) == []


def test_retrieve_relevant_memories_returns_matches():
    fake_db = MagicMock()
    fake_db.rpc.return_value.execute.return_value = SimpleNamespace(data=[{"content": "x"}])

    with patch.object(memory, "_extract_embedding", return_value=[0.1]):
        result = memory.retrieve_relevant_memories("athlete-1", "how's my training", fake_db)

    assert result == [{"content": "x"}]


def test_retrieve_relevant_memories_returns_empty_on_exception(capsys):
    fake_db = MagicMock()
    fake_db.rpc.side_effect = RuntimeError("rpc failed")

    with patch.object(memory, "_extract_embedding", return_value=[0.1]):
        result = memory.retrieve_relevant_memories("athlete-1", "query", fake_db)

    assert result == []
    assert "retrieval failed" in capsys.readouterr().out


def test_extract_and_save_memories_noop_for_empty_transcript():
    with patch.object(memory._llm_client.models, "generate_content") as mock_generate:
        memory.extract_and_save_memories("athlete-1", [], MagicMock())

    mock_generate.assert_not_called()


def test_extract_and_save_memories_saves_extracted_facts():
    conversation = [
        {"role": "user", "content": "I'm running Boston Marathon on April 20th aiming for sub 3 hours"},
        {"role": "assistant", "content": "Great goal!"},
    ]
    fake_response = SimpleNamespace(text='["Race goal: Boston Marathon sub 3:00 on April 20th"]')
    saved = []

    with patch.object(memory._llm_client.models, "generate_content", return_value=fake_response), patch.object(
        memory, "save_coach_memory", lambda athlete_id, fact, db: saved.append(fact)
    ):
        memory.extract_and_save_memories("athlete-1", conversation, MagicMock())

    assert saved == ["Race goal: Boston Marathon sub 3:00 on April 20th"]


def test_extract_and_save_memories_skips_when_no_json_array_found():
    fake_response = SimpleNamespace(text="no facts here")
    conversation = [{"role": "user", "content": "hello there, how's it going today"}]

    with patch.object(memory._llm_client.models, "generate_content", return_value=fake_response), patch.object(
        memory, "save_coach_memory"
    ) as mock_save:
        memory.extract_and_save_memories("athlete-1", conversation, MagicMock())

    mock_save.assert_not_called()


def test_extract_and_save_memories_skips_non_list_json():
    fake_response = SimpleNamespace(text='{"not": "a list"}')
    conversation = [{"role": "user", "content": "hello there, how's it going today"}]

    with patch.object(memory._llm_client.models, "generate_content", return_value=fake_response), patch.object(
        memory, "save_coach_memory"
    ) as mock_save:
        memory.extract_and_save_memories("athlete-1", conversation, MagicMock())

    mock_save.assert_not_called()


def test_extract_and_save_memories_swallows_generation_errors(capsys):
    conversation = [{"role": "user", "content": "hello there, how's it going today"}]
    with patch.object(memory._llm_client.models, "generate_content", side_effect=RuntimeError("gemini down")):
        memory.extract_and_save_memories("athlete-1", conversation, MagicMock())  # should not raise

    assert "extraction failed" in capsys.readouterr().out


def test_extract_and_save_memories_filters_facts_by_length():
    conversation = [{"role": "user", "content": "I'm training for a marathon in the fall, aiming for sub 4 hours"}]
    fake_response = SimpleNamespace(text='["too short", "A properly sized memorable fact about training goals here"]')
    saved = []

    with patch.object(memory._llm_client.models, "generate_content", return_value=fake_response), patch.object(
        memory, "save_coach_memory", lambda athlete_id, fact, db: saved.append(fact)
    ):
        memory.extract_and_save_memories("athlete-1", conversation, MagicMock())

    assert saved == ["A properly sized memorable fact about training goals here"]


def test_extract_embedding_final_fallback_uses_dict_style_access():
    class _DictLikeResp:
        embedding = None
        embeddings = None

        def __getitem__(self, key):
            if key == "embedding":
                return [0.9]
            raise KeyError(key)

    with patch.object(memory._client.models, "embed_content", return_value=_DictLikeResp()):
        assert memory._extract_embedding("text") == [0.9]


def test_save_coach_memory_continues_when_duplicate_check_raises():
    query = _MemQuery()
    query.execute = MagicMock(side_effect=RuntimeError("query failed"))
    db = _MemDb(query)
    with patch.object(memory, "_extract_embedding", return_value=[0.1]):
        memory.save_coach_memory("athlete-1", "New fact", db)
    assert len(query.inserted_payloads) == 1


def test_should_skip_rag_for_message_false_for_long_question_without_keywords():
    # Long enough, more than 4 words, contains "?" -> should NOT skip.
    assert memory.should_skip_rag_for_message("What do you think about my overall progress lately?") is False
