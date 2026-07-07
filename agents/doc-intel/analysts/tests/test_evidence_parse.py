"""U2 contract tests: format gates, page identity, and skip-with-reason."""

import io
import json

import pytest

from doc_intel_analysts.evidence import parse


def tiny_pdf(text: str) -> bytes:
    """Minimal one-page PDF with real extractable text (no fixture files)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return out.getvalue()


def tiny_jpeg() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (64, 48), (200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def test_pdf_happy_path_yields_all_layers(tmp_path):
    key = "WESTLAKE RESOURCES/WELL A/Drilling/report.pdf"
    doc = parse.parse_document(
        key, tiny_pdf("Well S733H stuck pipe at 9800 ft"), tmp_path,
        asset_team="WESTLAKE RESOURCES",
    )
    assert isinstance(doc, parse.ParsedDocument)
    assert doc.format_gate == "pdf" and doc.page_count == 1
    page = doc.pages[0]
    assert "S733H" in page.text
    assert page.screenshot_jpeg is not None and page.screenshot_jpeg[:2] == b"\xff\xd8"
    assert doc.chunks and all(c.page_id == page.page_id for c in doc.chunks)
    raw = json.loads((tmp_path / doc.doc_id / "parse.json").read_text())
    assert raw["s3key"] == key
    assert raw["pages"][0]["text_items"], "bounding boxes retained (R4)"


def test_page_identity_resolves_back_to_key():
    key = "TEAM/WELL B/logs/run1.las"
    doc = parse.parse_document(key, b"~Version\n WELL: B\n9800.5 12.3\n", None)
    assert doc.doc_id == parse.doc_id_for_key(key)
    assert ":" not in doc.doc_id and "/" not in doc.doc_id
    assert doc.pages[0].page_id == f"{doc.doc_id}:p1"
    assert all(c.page_id == f"{doc.doc_id}:p1" for c in doc.chunks)


def test_las_becomes_text_only_records():
    doc = parse.parse_document("t/w/log.las", b"DEPT GR\n9800 45\n" * 200, None)
    assert doc.format_gate == "text"
    assert doc.chunks and doc.pages[0].screenshot_jpeg is None


def test_xlsx_lands_in_skips_with_reason():
    skip = parse.parse_document("t/w/costs.xlsx", b"PK\x03\x04", None)
    assert isinstance(skip, parse.SkipRecord)
    assert "excel-family" in skip.reason


def test_corrupt_pdf_fails_into_skip_not_exception(tmp_path):
    skip = parse.parse_document("t/w/broken.pdf", b"%PDF-1.4 garbage", tmp_path)
    assert isinstance(skip, parse.SkipRecord)
    assert "parse failed" in skip.reason or "zero pages" in skip.reason


def test_empty_text_file_skips():
    skip = parse.parse_document("t/w/empty.txt", b"   \n", None)
    assert isinstance(skip, parse.SkipRecord)


def test_standalone_image_gets_screenshot_only():
    doc = parse.parse_document("t/w/plat.jpg", tiny_jpeg(), None)
    assert doc.format_gate == "image"
    assert doc.pages[0].screenshot_jpeg[:2] == b"\xff\xd8"
    assert doc.pages[0].text == "" and not doc.chunks


def test_text_native_size_cap_truncates_not_rejects():
    big = b"9800.5 12.3 45.6\n" * 200_000  # ~3.4 MB
    doc = parse.parse_document("t/w/big.csv", big, None)
    assert isinstance(doc, parse.ParsedDocument)
    assert doc.truncated is True
    assert len(doc.pages[0].text) == parse.TEXT_NATIVE_MAX_CHARS


def test_chunks_overlap_and_stay_page_bounded():
    text = "x" * 3000
    chunks = parse.chunk_text(text, "doc", 2)
    assert len(chunks) == 3
    assert all(c.page_num == 2 for c in chunks)
    assert chunks[0].chunk_id == "doc:p2:c0"


def test_unknown_extension_skips_with_named_reason():
    skip = parse.parse_document("t/w/data.kdex", b"?", None)
    assert isinstance(skip, parse.SkipRecord) and "kdex" in skip.reason
