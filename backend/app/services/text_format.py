"""Plain-text helpers for push notifications and other non-Markdown surfaces."""

import re


def normalize_markdown_notes(text: str | None) -> str:
    """Convert literal ``\\n`` sequences to real newlines for GFM pipe tables."""
    if not text:
        return ""
    return text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\r").strip()

_FENCED_CODE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_BOLD_ITALIC = re.compile(r"\*\*\*(.+?)\*\*\*", re.DOTALL)
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_UNDER = re.compile(r"__(.+?)__", re.DOTALL)
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.DOTALL)
_ITALIC_UNDER = re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", re.DOTALL)
_DISPLAY_MATH = re.compile(r"\$\$([^$]+)\$\$")
_INLINE_MATH = re.compile(r"\$([^$]+)\$")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_LIST_MARKER = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
_ORDERED_LIST = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def markdown_to_plain_text(text: str) -> str:
    """Convert coach Markdown to a single-line plain string for OS notifications."""
    if not text:
        return ""

    t = text.strip()

    # Fenced code blocks → inner text only (strip backticks wrapper)
    def _fence_repl(m: re.Match) -> str:
        inner = m.group(0).strip("`").strip()
        # drop optional language tag on first line
        if "\n" in inner:
            lines = inner.split("\n", 1)
            if lines[0] and not lines[0].startswith("|") and " " not in lines[0][:20]:
                inner = lines[1] if len(lines) > 1 else lines[0]
        return inner

    t = _FENCED_CODE.sub(_fence_repl, t)
    t = _INLINE_CODE.sub(r"\1", t)
    t = _IMAGE.sub(r"\1", t)
    t = _LINK.sub(r"\1", t)
    t = _BOLD_ITALIC.sub(r"\1", t)
    t = _BOLD.sub(r"\1", t)
    t = _BOLD_UNDER.sub(r"\1", t)
    t = _ITALIC.sub(r"\1", t)
    t = _ITALIC_UNDER.sub(r"\1", t)
    t = _DISPLAY_MATH.sub(r"\1", t)
    t = _INLINE_MATH.sub(r"\1", t)
    t = _HEADING.sub("", t)
    t = _BLOCKQUOTE.sub("", t)
    t = _LIST_MARKER.sub("", t)
    t = _ORDERED_LIST.sub("", t)
    t = _HTML_TAG.sub("", t)
    t = t.replace("|", " ")  # table pipes → spaces
    t = _WHITESPACE.sub(" ", t).strip()
    return t


def notification_preview(text: str, max_len: int = 120) -> str:
    """Plain-text preview for push notification body, truncated at a word boundary."""
    plain = markdown_to_plain_text(text)
    if len(plain) <= max_len:
        return plain

    cut = plain[:max_len]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"
