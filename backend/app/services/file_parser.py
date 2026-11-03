"""
Document parsing utilities for the ASTRAPHE AI coach.
Supports PDF, Word (.docx), CSV, and Excel (XLSX/XLS) file types.

Every parser stops as soon as it has _MAX_CHARS of text, and bounds the work it does
on a hostile file (page / sheet / row counts, zip expansion for XLSX), since only the
first _MAX_CHARS are ever used.
"""
from __future__ import annotations

import csv
import io
import zipfile

# Enough for a multi-week plan (a 12-week plan table is ~15-25k characters).
_MAX_CHARS = 30000
_MAX_ROWS = 2000
_MAX_PDF_PAGES = 60
_MAX_SHEETS = 8
# XLSX / DOCX are zips; refuse one that would expand far beyond any real training plan.
_MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


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


def _check_zip_expansion(file_bytes: bytes, limit: int, what: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            expanded = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        return  # not a zip: the format's own reader rejects it
    if expanded > limit:
        raise DocumentTooComplexError(f"{what} expands too large to parse")


def _check_xlsx_expansion(file_bytes: bytes) -> None:
    _check_zip_expansion(file_bytes, _MAX_XLSX_UNCOMPRESSED_BYTES, "spreadsheet")


def _cell_text(v: object) -> str:
    """Spreadsheet cell as text; whole-number floats lose the trailing .0 (xlrd gives 3.0)."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _rows_to_text(rows, total: int) -> tuple[list[str], int]:
    lines: list[str] = []
    for i, row in enumerate(rows):
        if i >= _MAX_ROWS:
            lines.append(f"... (truncated after {_MAX_ROWS} rows)")
            break
        cells = [_cell_text(v) for v in row]
        if any(cells):
            line = " | ".join(cells).rstrip(" |")
            lines.append(line)
            total += len(line) + 1
            if total >= _MAX_CHARS:
                break
    return lines, total


def parse_xlsx(file_bytes: bytes) -> str:
    import openpyxl
    _check_xlsx_expansion(file_bytes)
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    parts: list[str] = []
    total = 0
    for sheet_name in wb.sheetnames[:_MAX_SHEETS]:
        if total >= _MAX_CHARS:
            break
        rows, total = _rows_to_text(wb[sheet_name].iter_rows(values_only=True), total)
        if rows:
            parts.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows))
    return "\n\n".join(parts)[:_MAX_CHARS]


def parse_xls(file_bytes: bytes) -> str:
    """Legacy Excel 97-2003 (.xls); openpyxl only reads .xlsx."""
    import xlrd
    book = xlrd.open_workbook(file_contents=file_bytes, on_demand=True)
    parts: list[str] = []
    total = 0
    try:
        for idx in range(min(book.nsheets, _MAX_SHEETS)):
            if total >= _MAX_CHARS:
                break
            sh = book.sheet_by_index(idx)
            rows, total = _rows_to_text((sh.row_values(r) for r in range(sh.nrows)), total)
            if rows:
                parts.append(f"[Sheet: {sh.name}]\n" + "\n".join(rows))
    finally:
        book.release_resources()
    return "\n\n".join(parts)[:_MAX_CHARS]


def parse_docx(file_bytes: bytes) -> str:
    """Word (.docx): paragraphs and tables in document order. Training plans are usually a
    table (week / day / session); each row becomes "cell | cell | cell"."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _check_zip_expansion(file_bytes, _MAX_DOCX_UNCOMPRESSED_BYTES, "document")
    doc = Document(io.BytesIO(file_bytes))
    parts: list[str] = []
    total = 0
    for child in doc.element.body.iterchildren():
        if total >= _MAX_CHARS:
            break
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            if style.lower().startswith("heading"):
                text = f"## {text}"
            elif style.lower().startswith("list"):
                text = f"- {text}"
            parts.append(text)
            total += len(text) + 1
        elif tag == "tbl":
            table = Table(child, doc)
            rows: list[str] = []
            for i, row in enumerate(table.rows):
                if i >= _MAX_ROWS or total >= _MAX_CHARS:
                    break
                # Merged cells repeat across the row; keep each distinct cell once.
                cells: list[str] = []
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append(" ".join(cell.text.split()))
                if any(cells):
                    line = " | ".join(cells)
                    rows.append(line)
                    total += len(line) + 1
            if rows:
                parts.append("[Table]\n" + "\n".join(rows))
    return "\n\n".join(parts)[:_MAX_CHARS]


def parse_document(file_bytes: bytes, filename: str) -> str:
    """Parse a supported document and return its text content."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return parse_pdf(file_bytes)
    elif name.endswith(".csv"):
        return parse_csv(file_bytes)
    elif name.endswith(".xlsx"):
        return parse_xlsx(file_bytes)
    elif name.endswith(".xls"):
        return parse_xls(file_bytes)
    elif name.endswith(".docx"):
        return parse_docx(file_bytes)
    return ""
