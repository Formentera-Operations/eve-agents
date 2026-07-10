"""Parse corpus files into normalized page/chunk/asset records (U2).

Format gates (KTD4) — every file lands in exactly one of:

- PDF: full layers via LiteParse — page text, JPEG page screenshots (KTD5),
  extracted figures as assets, raw parse JSON (incl. text-item bounding
  boxes) retained under `.evidence/parsed/<doc_id>/` (R4).
- Text-native (LAS/CSV/TXT): text-only records — chunked and grep-able,
  size-capped per file, no screenshots.
- Standalone images (PNG/JPG/TIFF): a single screenshot record for CLIP,
  no text.
- Everything else: a skip with a visible reason — never silent (R2).

Identity: `doc_id` derives from the corpus S3 key (readable stem + short
hash, colon- and slash-free); `page_id = {doc_id}:p{page_num}` is the join
key across every table and back to provenance.
"""

import hashlib
import io
import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from doc_intel_analysts.evidence.config import RAW_BUCKET

# Chunking starts at the reference implementation's shape; tune only if
# retrieval metrics say so (plan: Assumptions).
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150

# KTD5: JPEG at bounded quality, targeting well under 0.5 MB/page.
JPEG_QUALITY = 70
JPEG_MAX_DIMENSION = 2200

# R5: project-owned replacement for PIL's decompression-bomb guard (which
# rejects anything above ~179 MP by default — too small for legitimate
# large-format well-log scans up to ~280 MP). Rationale for 600 MP: convert-
# to-RGB copies the decoded buffer, so peak transient decode during _to_jpeg
# is approximately (source bytes/px + 3) x pixels — at 600 MP that's ~1.8 GB
# for RGB sources (convert skipped, see KTD1) and ~2.4 GB for grayscale
# sources (convert not skipped). Checked strictly-above from header
# dimensions only, before any decode (R4).
IMAGE_PIXEL_CEILING = 600_000_000

# Text-native files are size-capped, not rejected: the head of an oversized
# LAS/CSV file is still searchable evidence.
TEXT_NATIVE_MAX_CHARS = 2_000_000
# R10 Option B (Rob, 2026-07-07): text-native files embed only their head
# chunks — sample LAS files averaged 728 chunks/doc, which priced Westlake
# at ~$64 and ~131GB. Grep and page reads are unaffected: the page row
# keeps the full (size-capped) text; only semantic-search granularity over
# deep numeric rows is given up.
TEXT_NATIVE_MAX_CHUNKS = 50

PDF_EXTENSIONS = {".pdf"}
TEXT_EXTENSIONS = {".las", ".csv", ".txt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass(frozen=True)
class PageRecord:
    page_id: str
    doc_id: str
    page_num: int
    text: str
    screenshot_jpeg: bytes | None
    width: int
    height: int


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    page_id: str
    doc_id: str
    page_num: int
    text: str


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    page_id: str
    doc_id: str
    page_num: int
    kind: str  # "figure" (extracted from a PDF page) | "image" (standalone file)
    image_jpeg: bytes


@dataclass(frozen=True)
class ParsedDocument:
    doc_id: str
    s3key: str
    asset_team: str
    format_gate: str  # "pdf" | "text" | "image"
    page_count: int
    pages: list[PageRecord] = field(default_factory=list)
    chunks: list[ChunkRecord] = field(default_factory=list)
    assets: list[AssetRecord] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class SkipRecord:
    s3key: str
    doc_id: str
    reason: str
    # True for parse exceptions (possibly environmental, retry next pass);
    # False for format-gate verdicts, and (KTD2) for the two deterministic
    # standalone-image failure classes — oversize header, unidentifiable
    # bytes — which are properties of the key/bytes, not the environment,
    # so retrying can never change the outcome. Everything else, including
    # the same two exception types raised from a non-image gate (e.g. a
    # PDF's embedded figure), stays retriable.
    retriable: bool = False


def doc_id_for_key(s3key: str) -> str:
    """Stable, readable, filesystem- and page_id-safe document identity.

    The slugged stem keeps hits human-scannable; the key hash keeps identity
    unique when different wells share filenames. Never contains ':' (the
    page_id separator) or path separators.
    """
    stem = Path(s3key).stem
    slug = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower()[:60] or "doc"
    digest = hashlib.sha1(s3key.encode()).hexdigest()[:8]
    return f"{slug}-{digest}"


def page_id_for(doc_id: str, page_num: int) -> str:
    return f"{doc_id}:p{page_num}"


def classify(s3key: str) -> str:
    """Map a corpus key to its format gate: pdf | text | image | skip:<reason>."""
    ext = Path(s3key).suffix.lower()
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in {".xls", ".xlsx", ".xlsm", ".xlsb"}:
        return "skip:excel-family deferred from v1 ingest (plan scope boundary)"
    if ext in {".xml", ".eml", ".zip", ".kdex"}:
        return f"skip:{ext.lstrip('.')} format deferred from v1 ingest (plan scope boundary)"
    return f"skip:unsupported extension {ext or '(none)'}"


def fetch_raw_bytes(s3key: str) -> bytes:
    """GetObject from the raw corpus bucket.

    New surface: the Python layer historically read only the derived bucket
    (`corpus.py`); evidence ingest is the first raw-archive consumer here.
    Read-only, no writes to the raw bucket ever.
    """
    import boto3

    body = boto3.client("s3").get_object(Bucket=RAW_BUCKET, Key=s3key)["Body"]
    return body.read()


def chunk_text(text: str, doc_id: str, page_num: int) -> list[ChunkRecord]:
    """Page-bounded ~1,200-char chunks with small overlap; never crosses pages."""
    pid = page_id_for(doc_id, page_num)
    chunks: list[ChunkRecord] = []
    start = 0
    index = 0
    stripped = text.strip()
    while start < len(stripped):
        piece = stripped[start : start + CHUNK_CHARS]
        if piece.strip():
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{pid}:c{index}",
                    page_id=pid,
                    doc_id=doc_id,
                    page_num=page_num,
                    text=piece,
                )
            )
            index += 1
        if start + CHUNK_CHARS >= len(stripped):
            break
        start += CHUNK_CHARS - CHUNK_OVERLAP
    return chunks


class _OversizeImageError(Exception):
    """A standalone image's declared pixel count exceeds IMAGE_PIXEL_CEILING.

    Raised from header metadata alone (KTD1) — no pixel data has been
    decoded when this fires. Carries the offending dimensions so the skip
    reason names them (R2).
    """

    def __init__(self, width: int, height: int, ceiling: int):
        self.width = width
        self.height = height
        super().__init__(
            f"image is {width}x{height} ({width * height:,} px), exceeds "
            f"project ceiling of {ceiling:,} px"
        )


def _to_jpeg(image_bytes: bytes) -> tuple[bytes, int, int]:
    """Re-encode any raster bytes as bounded JPEG (KTD5). Returns (jpeg, w, h)."""
    from PIL import Image

    # KTD1: PIL's own decompression-bomb guard (MAX_IMAGE_PIXELS) rejects
    # anything above ~179 MP, which is too small for legitimate large-format
    # well-log scans. Neutralize it and enforce IMAGE_PIXEL_CEILING below
    # instead — this is process-global, so any other PIL call site added to
    # this process from here on inherits NO decompression-bomb guard;
    # IMAGE_PIXEL_CEILING here is the sole guard for the whole process.
    Image.MAX_IMAGE_PIXELS = None

    img = Image.open(io.BytesIO(image_bytes))
    # Image.open reads only the header — dimensions are known before any
    # pixel data is decoded, so this check spends memory only on images we
    # go on to admit (R4).
    if img.width * img.height > IMAGE_PIXEL_CEILING:
        raise _OversizeImageError(img.width, img.height, IMAGE_PIXEL_CEILING)
    if img.mode != "RGB":
        # .convert("RGB") returns a new decoded copy while the source decode
        # is still resident in memory — skip it for sources already in RGB
        # so admitting an image at the ceiling doesn't double peak memory.
        img = img.convert("RGB")
    if max(img.size) > JPEG_MAX_DIMENSION:
        img.thumbnail((JPEG_MAX_DIMENSION, JPEG_MAX_DIMENSION))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue(), img.width, img.height


def parse_document(
    s3key: str,
    data: bytes,
    parsed_root: Path,
    *,
    asset_team: str = "",
) -> ParsedDocument | SkipRecord:
    """Run one corpus file through its format gate.

    Failures become SkipRecords with reasons, never exception escapes — the
    ledger is the visibility mechanism (R2).
    """
    doc_id = doc_id_for_key(s3key)
    gate = classify(s3key)
    if gate.startswith("skip:"):
        return SkipRecord(s3key=s3key, doc_id=doc_id, reason=gate[5:])
    try:
        if gate == "pdf":
            return _parse_pdf(s3key, doc_id, data, parsed_root, asset_team)
        if gate == "text":
            return _parse_text_native(s3key, doc_id, data, asset_team)
        return _parse_image(s3key, doc_id, data, asset_team)
    except Exception as exc:  # noqa: BLE001 — every failure must reach the ledger
        # KTD2: oversize and unidentifiable are deterministic properties of
        # the bytes — but only for the standalone-image gate. A PDF whose
        # *embedded* figure or page screenshot trips the same errors keeps
        # the default retriable path: one bad figure must not terminally
        # skip a whole multi-page PDF (KTD4: import where caught, not at
        # module level).
        from PIL import UnidentifiedImageError

        terminal = gate == "image" and isinstance(
            exc, (_OversizeImageError, UnidentifiedImageError)
        )
        return SkipRecord(
            s3key=s3key,
            doc_id=doc_id,
            reason=f"{gate} parse failed: {exc}",
            retriable=not terminal,
        )


def _parse_pdf(
    s3key: str, doc_id: str, data: bytes, parsed_root: Path, asset_team: str
) -> ParsedDocument:
    from liteparse import LiteParse

    parser = LiteParse(quiet=True)
    result = parser.parse(data)
    if not result.pages:
        raise ValueError("zero pages parsed")

    # screenshot() takes a path, not bytes — stage the PDF in a temp file.
    with tempfile.NamedTemporaryFile(suffix=".pdf") as staging:
        staging.write(data)
        staging.flush()
        shots = {s.page_num: s for s in parser.screenshot(Path(staging.name))}

    pages: list[PageRecord] = []
    chunks: list[ChunkRecord] = []
    for page in result.pages:
        shot = shots.get(page.page_num)
        jpeg, width, height = (
            _to_jpeg(shot.image_bytes) if shot else (None, 0, 0)
        )
        pages.append(
            PageRecord(
                page_id=page_id_for(doc_id, page.page_num),
                doc_id=doc_id,
                page_num=page.page_num,
                text=page.text,
                screenshot_jpeg=jpeg,
                width=width,
                height=height,
            )
        )
        chunks.extend(chunk_text(page.text, doc_id, page.page_num))

    assets = [
        AssetRecord(
            asset_id=f"{page_id_for(doc_id, img.page)}:a{img.id}",
            page_id=page_id_for(doc_id, img.page),
            doc_id=doc_id,
            page_num=img.page,
            kind="figure",
            image_jpeg=_to_jpeg(img.bytes)[0],
        )
        for img in result.images
    ]

    _retain_raw(parsed_root, doc_id, s3key, result)

    return ParsedDocument(
        doc_id=doc_id,
        s3key=s3key,
        asset_team=asset_team,
        format_gate="pdf",
        page_count=len(pages),
        pages=pages,
        chunks=chunks,
        assets=assets,
    )


def _retain_raw(parsed_root: Path, doc_id: str, s3key: str, result) -> None:
    """Persist the full parse output incl. bounding boxes (R4) so visual
    citation / escalation can be added later without re-parsing."""
    out_dir = parsed_root / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = {
        "s3key": s3key,
        "doc_id": doc_id,
        "pages": [
            {
                "page_num": p.page_num,
                "width": p.width,
                "height": p.height,
                "text": p.text,
                "markdown": p.markdown,
                "text_items": [
                    {
                        "text": t.text,
                        "x": t.x,
                        "y": t.y,
                        "width": t.width,
                        "height": t.height,
                    }
                    for t in p.text_items
                ],
            }
            for p in result.pages
        ],
        "images": [
            {"id": i.id, "page": i.page, "format": i.format} for i in result.images
        ],
    }
    (out_dir / "parse.json").write_text(json.dumps(raw))


def _parse_text_native(
    s3key: str, doc_id: str, data: bytes, asset_team: str
) -> ParsedDocument:
    text = data.decode("utf-8", errors="replace")
    truncated = len(text) > TEXT_NATIVE_MAX_CHARS
    if truncated:
        text = text[:TEXT_NATIVE_MAX_CHARS]
    if not text.strip():
        raise ValueError("empty text file")
    # Text-native files are one logical page: page 1 carries all chunks.
    pages = [
        PageRecord(
            page_id=page_id_for(doc_id, 1),
            doc_id=doc_id,
            page_num=1,
            text=text,
            screenshot_jpeg=None,
            width=0,
            height=0,
        )
    ]
    return ParsedDocument(
        doc_id=doc_id,
        s3key=s3key,
        asset_team=asset_team,
        format_gate="text",
        page_count=1,
        pages=pages,
        chunks=chunk_text(text, doc_id, 1)[:TEXT_NATIVE_MAX_CHUNKS],
        truncated=truncated,
    )


def _parse_image(
    s3key: str, doc_id: str, data: bytes, asset_team: str
) -> ParsedDocument:
    jpeg, width, height = _to_jpeg(data)
    pages = [
        PageRecord(
            page_id=page_id_for(doc_id, 1),
            doc_id=doc_id,
            page_num=1,
            text="",
            screenshot_jpeg=jpeg,
            width=width,
            height=height,
        )
    ]
    return ParsedDocument(
        doc_id=doc_id,
        s3key=s3key,
        asset_team=asset_team,
        format_gate="image",
        page_count=1,
        pages=pages,
    )
