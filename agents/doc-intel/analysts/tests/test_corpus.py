"""Contract tests for the analyst service's corpus layer.

The document_as_files contract is load-bearing and version-sensitive:
deepagents' StateBackend only sees seeded files when keys are ABSOLUTE
paths and values are FileData dicts ({"content", "encoding"}). Raw string
values crash read_file; relative keys are silently invisible to ls (the
failure mode that shipped in the first version and was caught only by a
live execution).
"""

from doc_intel_analysts.corpus import document_as_files, normalize

MARKDOWN_VIEW = {
    "kind": "markdown",
    "pages": [{"page": 1, "markdown": "X"}, {"page": 3, "markdown": "Y"}],
    "page_count": 3,
}


def test_files_are_filedata_dicts_under_absolute_paths():
    files = document_as_files("TEAM/WELL 1H/Financial/AFE/a.pdf", MARKDOWN_VIEW)
    assert files, "no files rendered"
    for path, data in files.items():
        assert path.startswith("/"), f"non-absolute seeded path: {path}"
        assert isinstance(data, dict) and data.get("encoding") == "utf-8", (
            f"value for {path} is not FileData"
        )
        assert isinstance(data["content"], str)


def test_page_files_carry_source_header_and_page_number():
    files = document_as_files("TEAM/WELL 1H/Financial/AFE/a.pdf", MARKDOWN_VIEW)
    page3 = next(v for k, v in files.items() if k.endswith("page-0003.md"))
    assert "<!-- source: TEAM/WELL 1H/Financial/AFE/a.pdf | page: 3 -->" in page3["content"]


def test_colliding_keys_stay_distinct():
    a = document_as_files("A/B__C", MARKDOWN_VIEW)
    b = document_as_files("A/B/C", MARKDOWN_VIEW)
    assert not set(a) & set(b)


def test_extraction_view_renders_single_json_file():
    view = {
        "kind": "extraction",
        "pages": [],
        "extraction": {"fields": {"afe_number": "52955"}, "field_pages": {"afe_number": [4]}},
        "page_count": 4,
    }
    files = document_as_files("T/W/AFE/x.pdf", view)
    (path, data), = files.items()
    assert path.endswith("/extraction.json") and path.startswith("/")
    assert '"source_key": "T/W/AFE/x.pdf"' in data["content"]


def test_normalize_converts_camelcase_cache_entries():
    view = normalize({"kind": "markdown", "pages": [{"page": 1, "markdown": "x"}], "pageCount": 1})
    assert view["page_count"] == 1 and "pageCount" not in view
