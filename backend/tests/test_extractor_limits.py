"""
Defensive-limits tests for DocumentExtractor (see P1-F).

Exercises every extractor method with deliberately oversized / hostile
inputs and asserts the output is bounded. No network IO.
"""
from __future__ import annotations

import io
from bs4 import BeautifulSoup

from app.services.content_service import (
    MAX_CELL_LEN,
    MAX_CSV_ROWS,
    MAX_HTML_TABLES,
    MAX_PAGE_TEXT_CHARS,
    MAX_TABLE_ROWS_PER_TAB,
    DocumentExtractor,
)


# ------------------------------------------------------------------
# extract_tables
# ------------------------------------------------------------------
def test_extract_tables_caps_number_of_tables():
    tables = "".join(
        f"<table><tr><td>t{i}c0</td></tr></table>"
        for i in range(MAX_HTML_TABLES + 10)
    )
    soup = BeautifulSoup(f"<html><body>{tables}</body></html>", "html.parser")
    out = DocumentExtractor.extract_tables(soup)
    # 先頭 MAX_HTML_TABLES のみを抽出し、テーブル n+1 (0-index では MAX)
    # のセル文字列は含まれないこと。
    assert f"t{MAX_HTML_TABLES - 1}c0" in out
    assert f"t{MAX_HTML_TABLES}c0" not in out
    # 超過した旨の注記を含む
    assert f"先頭 {MAX_HTML_TABLES} 件" in out


def test_extract_tables_caps_rows_per_table():
    rows = "".join(
        f"<tr><td>r{i}</td></tr>" for i in range(MAX_TABLE_ROWS_PER_TAB + 50)
    )
    soup = BeautifulSoup(f"<html><body><table>{rows}</table></body></html>", "html.parser")
    out = DocumentExtractor.extract_tables(soup)
    assert f"r{MAX_TABLE_ROWS_PER_TAB - 1}" in out
    assert f"r{MAX_TABLE_ROWS_PER_TAB}" not in out


def test_extract_tables_truncates_cell_content():
    huge = "A" * (MAX_CELL_LEN * 3)
    soup = BeautifulSoup(
        f"<html><body><table><tr><td>{huge}</td></tr></table></body></html>", "html.parser",
    )
    out = DocumentExtractor.extract_tables(soup)
    # 切り詰められていること: 生の A の連続が max+small に収まる
    assert len(out) < MAX_CELL_LEN * 3


# ------------------------------------------------------------------
# extract_csv_content
# ------------------------------------------------------------------
def test_extract_csv_caps_rows():
    rows = "\n".join(f"a{i},b{i}" for i in range(MAX_CSV_ROWS + 20))
    content = rows.encode("utf-8")
    out = DocumentExtractor.extract_csv_content("https://ex/test.csv", content)
    assert f"a{MAX_CSV_ROWS - 1}" in out
    assert f"a{MAX_CSV_ROWS}" not in out
    assert f"先頭 {MAX_CSV_ROWS} 行" in out


def test_extract_csv_truncates_cell():
    huge = "B" * (MAX_CELL_LEN * 3)
    content = f"hdr\n{huge}".encode("utf-8")
    out = DocumentExtractor.extract_csv_content("https://ex/x.csv", content)
    assert len(out) < MAX_CELL_LEN * 3


def test_extract_csv_empty_input_is_empty_output():
    assert DocumentExtractor.extract_csv_content("https://ex/x.csv", b"") == ""


# ------------------------------------------------------------------
# extract_page_text
# ------------------------------------------------------------------
def test_extract_page_text_caps_total_chars():
    huge = "x" * (MAX_PAGE_TEXT_CHARS * 2)
    soup = BeautifulSoup(f"<html><body>{huge}</body></html>", "html.parser")
    out = DocumentExtractor.extract_page_text(soup)
    # Marker adds a few chars; allow a small slack.
    assert len(out) <= MAX_PAGE_TEXT_CHARS + 4


def test_extract_page_text_strips_script_and_style():
    html = (
        "<html><body>"
        "<script>var pwned=1;</script>"
        "<style>body{color:red}</style>"
        "<p>visible</p>"
        "</body></html>"
    )
    soup = BeautifulSoup(html, "html.parser")
    out = DocumentExtractor.extract_page_text(soup)
    assert "pwned" not in out
    assert "color:red" not in out
    assert "visible" in out


# ------------------------------------------------------------------
# extract_pdf_content (round-trip via a real in-memory pypdf doc)
# ------------------------------------------------------------------
def test_extract_pdf_handles_corrupt_bytes_without_raising():
    # Garbage bytes must not crash the extractor — it logs + returns ''.
    out = DocumentExtractor.extract_pdf_content("https://ex/x.pdf", b"not a pdf")
    assert out == ""
