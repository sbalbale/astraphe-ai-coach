"""
Document parsing utilities for the ASTRAPHE AI coach.
Supports PDF, CSV, and Excel (XLSX/XLS) file types.

Every parser stops as soon as it has _MAX_CHARS of text, and bounds the work it does
on a hostile file (page / sheet / row counts, zip expansion for XLSX), since only the
first _MAX_CHARS are ever used.
"""
from __future__ import annotations

import csv
import io
import zipfile

_MAX_CHARS = 8000
_MAX_ROWS = 500
_MAX_PDF_PAGES = 50
_MAX_SHEETS = 5
# An XLSX is a zip; refuse one that would expand far beyond any real training log.
_MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


class DocumentTooComplexError(ValueError):
    """The file is outside the bounds we're willing to parse."""


def parse_pdf(file_bytes: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    parts: list[str] = []
    total = 0
    for i, page in enumerate(reader.pages, 1):
        if i > _MAX_PDF_PAGES or total >= _MAX_CHARS:
            break
        text = (page.extract_text() or "").strip()
        if text:
            chunk = f"[Page {i}]\n{text}"
            parts.append(chunk)
            total += len(chunk) + 2
    return "\n\n".join(parts)[:_MAX_CHARS]


def parse_csv(file_bytes: bytes) -> str:
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    lines: list[str] = []
    total = 0
    for i, row in enumerate(reader):
        if i >= _MAX_ROWS:
            lines.append(f"... (truncated after {_MAX_ROWS} rows)")
            break
        line = " | ".join(str(c) for c in row)
        lines.append(line)
        total += len(line) + 1
        if total >= _MAX_CHARS:
            break
    return "\n".join(lines)[:_MAX_CHARS]


def _check_xlsx_expansion(file_bytes: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            expanded = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        return  # legacy .xls or not a zip: openpyxl rejects it itself
    if expanded > _MAX_XLSX_UNCOMPRESSED_BYTES:
        raise DocumentTooComplexError("spreadsheet expands too large to parse")


def parse_xlsx(file_bytes: bytes) -> str:
    import openpyxl
    _check_xlsx_expansion(file_bytes)
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    parts: list[str] = []
    total = 0
    for sheet_name in wb.sheetnames[:_MAX_SHEETS]:
        if total >= _MAX_CHARS:
            break
        ws = wb[sheet_name]
        rows: list[str] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= _MAX_ROWS:
                rows.append(f"... (truncated after {_MAX_ROWS} rows)")
                break
            if any(v is not None for v in row):
                line = " | ".join("" if v is None else str(v) for v in row)
                rows.append(line)
                total += len(line) + 1
                if total >= _MAX_CHARS:
                    break
        if rows:
            parts.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows))
    return "\n\n".join(parts)[:_MAX_CHARS]


def parse_document(file_bytes: bytes, filename: str) -> str:
    """Parse a supported document and return its text content."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return parse_pdf(file_bytes)
    elif name.endswith(".csv"):
        return parse_csv(file_bytes)
    elif name.endswith((".xlsx", ".xls")):
        return parse_xlsx(file_bytes)
    return ""
