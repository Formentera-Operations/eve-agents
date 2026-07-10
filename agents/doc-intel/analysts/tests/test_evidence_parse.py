"""U2 contract tests: format gates, page identity, and skip-with-reason."""

import io
import json
import struct

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


def huge_bmp_header(width: int, height: int) -> bytes:
    """Minimal BMP file+info header declaring the given dimensions, with no
    pixel data following. PIL's BMP plugin reads width/height (and mode)
    from these 54 header bytes at `Image.open` time and only decodes pixel
    rows lazily on `.load()` — so this fixture exercises the header-only
    pixel check (R4) without allocating any real pixel buffer. Keyed with a
    supported *image* extension in tests (not `.bmp`, which isn't a
    supported extension and would hit the format gate before the pixel
    check) — PIL sniffs content, not the extension, so it identifies this
    correctly as BMP regardless of the key's suffix.
    """
    header_size = 14 + 40
    file_header = b"BM" + struct.pack("<IHHI", header_size, 0, 0, header_size)
    info_header = struct.pack(
        "<IiiHHIIiiII",
        40,  # biSize
        width,  # biWidth
        height,  # biHeight
        1,  # biPlanes
        24,  # biBitCount (24-bit RGB, no palette)
        0,  # biCompression (BI_RGB)
        0,  # biSizeImage
        0,  # biXPelsPerMeter
        0,  # biYPelsPerMeter
        0,  # biClrUsed
        0,  # biClrImportant
    )
    return file_header + info_header


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


def test_text_native_embeds_head_chunks_only():
    """R10 Option B: chunk records cap at TEXT_NATIVE_MAX_CHUNKS while the
    page row keeps the full text for grep."""
    big = b"9800.5 12.3 45.6 GR SP RES\n" * 20_000  # ~540k chars
    doc = parse.parse_document("t/w/deep.las", big, None)
    assert len(doc.chunks) == parse.TEXT_NATIVE_MAX_CHUNKS
    assert len(doc.pages[0].text) == len(big)


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


def test_oversize_image_header_only_terminal_skip():
    """R1/R2/R4/KTD1: a header declaring >600 MP is rejected from header
    metadata alone (no pixel data in the fixture), terminally, with the
    declared dimensions and the project's own reason text — not PIL's
    "decompression bomb" message — proving PIL's stock guard was replaced."""
    huge = huge_bmp_header(30_000, 30_000)  # 900,000,000 px
    skip = parse.parse_document("t/w/huge.png", huge, None)
    assert isinstance(skip, parse.SkipRecord)
    assert skip.retriable is False
    assert "30000" in skip.reason and "900000000" in skip.reason.replace(",", "")
    assert "decompression bomb" not in skip.reason.lower()
    assert str(parse.IMAGE_PIXEL_CEILING) in skip.reason.replace(",", "")


def test_oversize_boundary_via_patched_ceiling(monkeypatch):
    """Boundary is strictly-above: below a patched ceiling it terminally
    skips with dims in the reason; exactly at the ceiling it parses."""
    fixture = tiny_jpeg()
    pixels = 64 * 48

    monkeypatch.setattr(parse, "IMAGE_PIXEL_CEILING", pixels - 1)
    skip = parse.parse_document("t/w/plat.jpg", fixture, None)
    assert isinstance(skip, parse.SkipRecord)
    assert skip.retriable is False
    assert "64" in skip.reason and "48" in skip.reason

    monkeypatch.setattr(parse, "IMAGE_PIXEL_CEILING", pixels)
    doc = parse.parse_document("t/w/plat.jpg", fixture, None)
    assert isinstance(doc, parse.ParsedDocument)
    assert doc.format_gate == "image"


def test_unidentifiable_image_terminal_skip():
    """R3: bytes PIL cannot identify at all (not merely oversize) are a
    deterministic content failure — terminal, not retriable."""
    skip = parse.parse_document("t/w/broken.png", b"not an image at all", None)
    assert isinstance(skip, parse.SkipRecord)
    assert skip.retriable is False
    assert "identify" in skip.reason.lower()


def test_pdf_gate_keeps_unidentifiable_error_retriable(tmp_path, monkeypatch):
    """KTD2: terminal classification is image-gate-only — a PDF whose
    embedded-figure handling raises PIL's UnidentifiedImageError must not
    terminally skip the whole document."""
    from PIL import UnidentifiedImageError

    def boom(*args, **kwargs):
        raise UnidentifiedImageError("cannot identify image file <fake>")

    monkeypatch.setattr(parse, "_parse_pdf", boom)
    skip = parse.parse_document("t/w/report.pdf", b"%PDF-1.4 fake", tmp_path)
    assert isinstance(skip, parse.SkipRecord)
    assert skip.retriable is True


def test_pdf_gate_keeps_oversize_error_retriable(tmp_path, monkeypatch):
    """KTD2: same scoping for the oversize exception — a corrupt/oversize
    embedded figure must not terminally skip the whole PDF."""
    oversize_error_cls = parse._OversizeImageError  # resolved eagerly: a
    # missing attribute here must surface as a collection-time AttributeError,
    # not get swallowed by parse_document's own except-block under test.

    def boom(*args, **kwargs):
        raise oversize_error_cls(30_000, 30_000, parse.IMAGE_PIXEL_CEILING)

    monkeypatch.setattr(parse, "_parse_pdf", boom)
    skip = parse.parse_document("t/w/report.pdf", b"%PDF-1.4 fake", tmp_path)
    assert isinstance(skip, parse.SkipRecord)
    assert skip.retriable is True


def test_image_transient_oserror_stays_retriable(monkeypatch):
    """R6: non-deterministic failures in the image path keep the existing
    retriable semantics — only the two deterministic classes are terminal."""

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(parse, "_to_jpeg", boom)
    skip = parse.parse_document("t/w/plat.jpg", tiny_jpeg(), None)
    assert isinstance(skip, parse.SkipRecord)
    assert skip.retriable is True
