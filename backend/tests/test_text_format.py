from app.services.text_format import markdown_to_plain_text, normalize_markdown_notes, notification_preview

HRV_REPLY = (
    "Given how much your HRV has dipped—**2.12 SD below your baseline**—"
    "I would actually recommend **complete rest** over an active recovery session "
    "like a bike or walk. 🧘‍♂️\n\n"
    'I know the instinct is to "flush" the legs, but here is the physiological reality: '
    "even a \"chill\" ride or walk requires your nervous system to engage to maintain "
    "movement and balance. Right now, your autonomic nervous system is signaling that "
    "it's struggling to recover from your recent volume inc"
)


def test_markdown_to_plain_text_strips_bold():
    plain = markdown_to_plain_text(HRV_REPLY)
    assert "**" not in plain
    assert "2.12 SD below your baseline" in plain
    assert "complete rest" in plain
    assert "🧘‍♂️" in plain


def test_markdown_to_plain_text_strips_links_and_code():
    md = "See [this article](https://example.com) and `inline code`."
    plain = markdown_to_plain_text(md)
    assert "**" not in plain
    assert "this article" in plain
    assert "https://" not in plain
    assert "inline code" in plain
    assert "`" not in plain


def test_markdown_to_plain_text_collapses_whitespace():
    md = "Line one.\n\nLine two.\n\n  Line three."
    plain = markdown_to_plain_text(md)
    assert "\n" not in plain
    assert plain == "Line one. Line two. Line three."


def test_notification_preview_no_asterisks():
    preview = notification_preview(HRV_REPLY)
    assert "**" not in preview
    assert len(preview) <= 121  # 120 + ellipsis char


def test_notification_preview_word_boundary_truncation():
    preview = notification_preview(HRV_REPLY, max_len=120)
    assert preview.endswith("…")
    # Should not end mid-word like "inc"
    assert not preview.rstrip("…").endswith(" inc")


def test_notification_preview_short_text_unchanged():
    short = "Rest today. **No ride.**"
    preview = notification_preview(short)
    assert preview == "Rest today. No ride."
    assert "…" not in preview


def test_normalize_markdown_notes_none_and_empty():
    assert normalize_markdown_notes(None) == ""
    assert normalize_markdown_notes("") == ""


def test_normalize_markdown_notes_unescapes_newlines():
    src = "| A | B |\\n| --- | --- |\\n| 1 | 2 |"
    out = normalize_markdown_notes(src)
    assert "\\n" not in out
    assert "\n| --- | --- |" in out


def test_normalize_markdown_notes_rejects_non_string_types():
    assert normalize_markdown_notes({"phase": "warmup"}) == ""  # type: ignore[arg-type]
    assert normalize_markdown_notes(["row"]) == ""  # type: ignore[arg-type]
    assert normalize_markdown_notes(42) == ""  # type: ignore[arg-type]
