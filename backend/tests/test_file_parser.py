from __future__ import annotations

import io

from app.services import file_parser


def test_parse_csv_joins_columns_with_pipe():
    csv_bytes = b"name,age\nAlice,30\nBob,25\n"

    result = file_parser.parse_csv(csv_bytes)

    assert "name | age" in result
    assert "Alice | 30" in result
    assert "Bob | 25" in result


def test_parse_csv_truncates_after_max_rows(monkeypatch):
    monkeypatch.setattr(file_parser, "_MAX_ROWS", 2)
    csv_bytes = b"\n".join(f"row{i}".encode() for i in range(5))

    result = file_parser.parse_csv(csv_bytes)

    assert "truncated after 2 rows" in result


def test_parse_csv_truncates_output_length(monkeypatch):
    monkeypatch.setattr(file_parser, "_MAX_CHARS", 10)
    csv_bytes = b"a,b,c,d,e,f,g,h,i,j,k,l,m,n"

    result = file_parser.parse_csv(csv_bytes)

    assert len(result) == 10


def test_parse_xlsx_extracts_sheet_rows():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Header1", "Header2"])
    ws.append(["v1", "v2"])
    buf = io.BytesIO()
    wb.save(buf)

    result = file_parser.parse_xlsx(buf.getvalue())

    assert "[Sheet: Sheet1]" in result
    assert "Header1 | Header2" in result
    assert "v1 | v2" in result


def test_parse_xlsx_skips_fully_empty_rows():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["a"])
    ws.append([None, None])
    ws.append(["b"])
    buf = io.BytesIO()
    wb.save(buf)

    result = file_parser.parse_xlsx(buf.getvalue())

    # The fully-empty middle row is skipped, and trailing empty cells don't leave "a | ".
    assert result == "[Sheet: Sheet]\na\nb"


def test_parse_pdf_extracts_text_per_page():
    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)

    # A blank page has no extractable text, so parse_pdf should return an
    # empty string rather than raising.
    result = file_parser.parse_pdf(buf.getvalue())
    assert result == ""


def test_parse_document_dispatches_by_extension():
    assert file_parser.parse_document(b"a,b\n1,2\n", "data.csv") != ""
    assert file_parser.parse_document(b"a,b\n1,2\n", "DATA.CSV") != ""
    assert file_parser.parse_document(b"anything", "notes.txt") == ""


def test_parse_document_dispatches_xlsx_xls_and_docx(monkeypatch):
    monkeypatch.setattr(file_parser, "parse_xlsx", lambda b: "xlsx")
    monkeypatch.setattr(file_parser, "parse_xls", lambda b: "xls")
    monkeypatch.setattr(file_parser, "parse_docx", lambda b: "docx")

    assert file_parser.parse_document(b"x", "sheet.xlsx") == "xlsx"
    # Legacy .xls needs xlrd; openpyxl only reads .xlsx.
    assert file_parser.parse_document(b"x", "sheet.xls") == "xls"
    assert file_parser.parse_document(b"x", "Plan.DOCX") == "docx"


def _docx_bytes(build) -> bytes:
    from docx import Document

    doc = Document()
    build(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_parse_docx_keeps_headings_lists_and_tables_in_order():
    def build(doc):
        doc.add_heading("Week 1", level=1)
        doc.add_paragraph("Base block. Keep it easy.")
        doc.add_paragraph("Fuel 60 g/h", style="List Bullet")
        t = doc.add_table(rows=3, cols=3)
        for r, row in enumerate([["Day", "Session", "Duration"], ["Mon", "Rest", ""], ["Tue", "Threshold 2x20", "90"]]):
            for c, v in enumerate(row):
                t.cell(r, c).text = v
        doc.add_paragraph("Week 2 follows.")

    text = file_parser.parse_docx(_docx_bytes(build))

    assert text.index("## Week 1") < text.index("Base block") < text.index("[Table]") < text.index("Week 2 follows")
    assert "- Fuel 60 g/h" in text
    assert "Day | Session | Duration" in text
    assert "Tue | Threshold 2x20 | 90" in text


def test_parse_docx_lists_a_merged_cell_once():
    def build(doc):
        t = doc.add_table(rows=1, cols=3)
        merged = t.cell(0, 0).merge(t.cell(0, 1))
        merged.text = "Week 1"
        t.cell(0, 2).text = "Build"

    assert "Week 1 | Build" in file_parser.parse_docx(_docx_bytes(build))


def test_parse_docx_stops_at_max_chars(monkeypatch):
    monkeypatch.setattr(file_parser, "_MAX_CHARS", 50)

    def build(doc):
        for i in range(40):
            doc.add_paragraph(f"Session line number {i}")

    assert len(file_parser.parse_docx(_docx_bytes(build))) <= 50


def test_parse_docx_rejects_a_zip_bomb(monkeypatch):
    import pytest

    monkeypatch.setattr(file_parser, "_MAX_DOCX_UNCOMPRESSED_BYTES", 100)
    with pytest.raises(file_parser.DocumentTooComplexError):
        file_parser.parse_docx(_docx_bytes(lambda doc: doc.add_paragraph("x" * 1000)))


def test_cell_text_drops_trailing_zero_from_whole_floats():
    assert file_parser._cell_text(3.0) == "3"
    assert file_parser._cell_text(2.5) == "2.5"
    assert file_parser._cell_text(None) == ""
    assert file_parser._cell_text("  Z2  ") == "Z2"


def test_parse_document_dispatches_pdf(monkeypatch):
    monkeypatch.setattr(file_parser, "parse_pdf", lambda b: "pdf-text")

    assert file_parser.parse_document(b"x", "report.pdf") == "pdf-text"


def test_parse_pdf_extracts_text_when_page_has_content():
    from unittest.mock import MagicMock, patch

    fake_page = MagicMock()
    fake_page.extract_text.return_value = "Hello from a real PDF page"
    fake_reader = MagicMock()
    fake_reader.pages = [fake_page]

    with patch("pypdf.PdfReader", return_value=fake_reader):
        result = file_parser.parse_pdf(b"fake-pdf-bytes")

    assert "Hello from a real PDF page" in result
    assert "[Page 1]" in result


def test_parse_xlsx_truncates_after_max_rows(monkeypatch):
    import openpyxl

    monkeypatch.setattr(file_parser, "_MAX_ROWS", 3)
    wb = openpyxl.Workbook()
    ws = wb.active
    for i in range(10):
        ws.append([f"row{i}"])
    buf = __import__("io").BytesIO()
    wb.save(buf)

    result = file_parser.parse_xlsx(buf.getvalue())
    assert "truncated after 3 rows" in result
