from app.services.text_format import markdown_to_plain_text, notification_preview


def test_markdown_to_plain_text_strips_language_tag_from_fenced_block():
    md = "```python\nprint('hi')\n```"
    plain = markdown_to_plain_text(md)
    assert "python" not in plain
    assert "print" in plain


def test_markdown_to_plain_text_keeps_single_line_fence_content():
    md = "```short```"
    plain = markdown_to_plain_text(md)
    assert plain == "short"


def test_notification_preview_truncates_without_space_boundary():
    long_word = "x" * 200
    preview = notification_preview(long_word, max_len=50)
    assert preview.endswith("…")
    assert len(preview) == 51
