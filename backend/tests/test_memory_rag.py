from app.services.memory import should_skip_rag_for_message


def test_skip_rag_short_greeting():
    assert should_skip_rag_for_message("hi") is True
    assert should_skip_rag_for_message("thanks!") is True


def test_use_rag_for_plan_keywords():
    assert should_skip_rag_for_message("can you build my training plan for next week?") is False
    assert should_skip_rag_for_message("my knee hurts after long runs") is False
