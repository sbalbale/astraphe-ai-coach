"""Chat attachments: documents on a message, in history, and in the messages API."""
from __future__ import annotations

from app.routers import coach
from app.services import ai_coach


def _payload(**kw):
    return coach.ChatMessage(message=kw.pop("message", "Load this plan"), **kw)


def test_message_documents_takes_named_documents_and_legacy_text():
    p = _payload(
        documents=[{"name": "Base block.docx", "content": "Week 1 | Mon | Rest"}, {"name": "empty.pdf", "content": "   "}],
        document_contents=["legacy text"],
    )
    docs = coach._message_documents(p)
    assert docs == [
        {"name": "Base block.docx", "kind": "docx", "content": "Week 1 | Mon | Rest"},
        {"name": "Document 1", "kind": "file", "content": "legacy text"},
    ]


def test_documents_are_capped_in_size_and_count():
    import pytest
    from pydantic import ValidationError

    p = _payload(documents=[{"name": "big.pdf", "content": "x" * (coach._MAX_DOC_CHARS + 500)}])
    assert len(p.documents[0].content) == coach._MAX_DOC_CHARS
    with pytest.raises(ValidationError):
        _payload(documents=[{"name": f"{i}.pdf", "content": "x"} for i in range(4)])


def test_message_with_documents_names_each_document():
    out = coach._message_with_documents("What do you think?", [{"name": "plan.xlsx", "kind": "xlsx", "content": "Mon | Rest"}])
    assert out == "[ATTACHED DOCUMENT: plan.xlsx]\nMon | Rest\n\n[ATHLETE MESSAGE]\nWhat do you think?"
    assert coach._message_with_documents("hi", []) == "hi"


def test_history_replays_earlier_documents_but_not_the_message_being_answered():
    history = [
        {"role": "user", "content": "Here's my plan", "attachments": [{"name": "plan.docx", "content": "Week 1 | Threshold"}]},
        {"role": "ai", "content": "<response>Got it.</response>"},
        {"role": "user", "content": "Now with this one", "attachments": [{"name": "new.pdf", "content": "NEW TEXT"}]},
    ]
    contents = ai_coach._history_to_gemini_contents(history)
    texts = [c.parts[0].text for c in contents]
    assert texts[0].startswith("[ATTACHED DOCUMENT: plan.docx]\nWeek 1 | Threshold")
    assert texts[0].endswith("[ATHLETE MESSAGE]\nHere's my plan")
    # The newest user message's document travels with the current turn instead.
    assert "NEW TEXT" not in texts[-1]


def test_history_document_budget_keeps_the_newest(monkeypatch):
    monkeypatch.setattr(ai_coach, "_HISTORY_DOC_CHARS", 10)
    history = [
        {"role": "user", "content": "old", "attachments": [{"name": "old.pdf", "content": "OLDOLDOLDOLD"}]},
        {"role": "user", "content": "newer", "attachments": [{"name": "newer.pdf", "content": "NEWER"}]},
        {"role": "user", "content": "current"},
    ]
    pre = ai_coach._attachment_preface(history)
    assert "NEWER" in pre[1]
    assert pre[0].startswith("[ATTACHED DOCUMENT: old.pdf]\nOLDOL")  # 5 chars of budget left
    monkeypatch.setattr(ai_coach, "_HISTORY_DOC_CHARS", 5)
    assert ai_coach._attachment_preface(history)[0] == "[ATTACHED DOCUMENT: old.pdf (text omitted)]"


def test_insert_message_stores_attachments_and_titles_from_the_file(monkeypatch):
    from unittest.mock import MagicMock

    db = MagicMock()
    titles = []
    monkeypatch.setattr(coach, "_maybe_set_conversation_title", lambda _db, _a, _c, title: titles.append(title))
    monkeypatch.setattr(coach, "_touch_conversation", lambda *a: None)
    docs = [{"name": "12 week plan.pdf", "kind": "pdf", "content": "..."}]

    coach._insert_message(db, "ath", "conv", "user", "", None, docs)

    row = db.table.return_value.insert.call_args[0][0]
    assert row["attachments"] == docs
    assert titles and "12 week plan" in titles[0]
