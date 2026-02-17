"""Tests for Google Drive ingestion — targeting pain points."""

import hashlib
from types import SimpleNamespace

import pytest

# Import the pure functions we can test without API calls
from src.ingestion.drive import (
    EXPORT_MIME_MAP,
    MAX_DOWNLOAD_BYTES,
    TEXT_MIME_PREFIXES,
    _build_folder_path,
    _content_hash,
    _is_google_workspace_type,
    _should_extract_text,
)


# --- MIME type classification ---


class TestIsGoogleWorkspaceType:
    def test_google_doc(self):
        assert _is_google_workspace_type("application/vnd.google-apps.document") is True

    def test_google_sheet(self):
        assert _is_google_workspace_type("application/vnd.google-apps.spreadsheet") is True

    def test_google_slides(self):
        assert _is_google_workspace_type("application/vnd.google-apps.presentation") is True

    def test_google_folder(self):
        assert _is_google_workspace_type("application/vnd.google-apps.folder") is True

    def test_regular_pdf(self):
        assert _is_google_workspace_type("application/pdf") is False

    def test_text_plain(self):
        assert _is_google_workspace_type("text/plain") is False

    def test_empty_string(self):
        assert _is_google_workspace_type("") is False


class TestShouldExtractText:
    """These tests verify which file types we actually attempt to extract text from."""

    def test_google_doc_yes(self):
        assert _should_extract_text("application/vnd.google-apps.document") is True

    def test_google_sheet_yes(self):
        assert _should_extract_text("application/vnd.google-apps.spreadsheet") is True

    def test_google_slides_yes(self):
        assert _should_extract_text("application/vnd.google-apps.presentation") is True

    def test_google_folder_no(self):
        """Folders have no content — don't try to extract."""
        assert _should_extract_text("application/vnd.google-apps.folder") is False

    def test_google_drawing_no(self):
        """Drawings can't be exported as text."""
        assert _should_extract_text("application/vnd.google-apps.drawing") is False

    def test_google_form_no(self):
        assert _should_extract_text("application/vnd.google-apps.form") is False

    def test_text_plain_yes(self):
        assert _should_extract_text("text/plain") is True

    def test_text_csv_yes(self):
        assert _should_extract_text("text/csv") is True

    def test_text_html_yes(self):
        assert _should_extract_text("text/html") is True

    def test_json_yes(self):
        assert _should_extract_text("application/json") is True

    def test_xml_yes(self):
        assert _should_extract_text("application/xml") is True

    def test_javascript_yes(self):
        assert _should_extract_text("application/javascript") is True

    def test_pdf_no(self):
        """PDFs need OCR — we don't handle that in the basic ingestion."""
        assert _should_extract_text("application/pdf") is False

    def test_image_no(self):
        assert _should_extract_text("image/png") is False

    def test_zip_no(self):
        assert _should_extract_text("application/zip") is False

    def test_binary_no(self):
        assert _should_extract_text("application/octet-stream") is False


class TestExportMimeMap:
    """Verify the export MIME map covers all Google Workspace types we care about."""

    def test_document_exports_text(self):
        assert EXPORT_MIME_MAP["application/vnd.google-apps.document"] == "text/plain"

    def test_spreadsheet_exports_csv(self):
        assert EXPORT_MIME_MAP["application/vnd.google-apps.spreadsheet"] == "text/csv"

    def test_presentation_exports_text(self):
        assert EXPORT_MIME_MAP["application/vnd.google-apps.presentation"] == "text/plain"

    def test_folder_is_none(self):
        """Folders should explicitly be None to signal 'skip'."""
        assert EXPORT_MIME_MAP["application/vnd.google-apps.folder"] is None

    def test_drawing_is_none(self):
        assert EXPORT_MIME_MAP["application/vnd.google-apps.drawing"] is None

    def test_all_values_are_string_or_none(self):
        for key, val in EXPORT_MIME_MAP.items():
            assert val is None or isinstance(val, str), f"Bad value for {key}: {val}"


# --- Content hash ---


class TestContentHash:
    def test_deterministic(self):
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_content_different_hash(self):
        assert _content_hash("hello") != _content_hash("world")

    def test_is_sha256(self):
        result = _content_hash("test")
        assert len(result) == 64  # SHA-256 hex = 64 chars
        assert result == hashlib.sha256(b"test").hexdigest()

    def test_empty_string(self):
        result = _content_hash("")
        assert len(result) == 64

    def test_unicode(self):
        result = _content_hash("日本語テスト")
        assert len(result) == 64


# --- Folder path building ---

class _MockService:
    """Mock Drive service for testing folder path resolution."""

    def __init__(self, folder_tree: dict):
        """folder_tree: {id: {"name": str, "parents": [str] or []}}"""
        self._tree = folder_tree

    def files(self):
        return self

    def get(self, fileId, fields=None):
        return self

    def execute(self):
        # The fileId was passed via get() — we track it on the mock
        data = self._tree.get(self._last_id, {})
        return {
            "id": self._last_id,
            "name": data.get("name", ""),
            "parents": data.get("parents", []),
        }

    def get(self, fileId, fields=None):
        self._last_id = fileId
        return self


class TestBuildFolderPath:
    def test_empty_parents(self):
        service = _MockService({})
        assert _build_folder_path(service, [], {}) == ""

    def test_single_level(self):
        service = _MockService({
            "folder1": {"name": "Documents", "parents": []},
        })
        result = _build_folder_path(service, ["folder1"], {})
        assert result == "Documents"

    def test_two_levels(self):
        service = _MockService({
            "folder2": {"name": "Projects", "parents": ["folder1"]},
            "folder1": {"name": "My Drive", "parents": []},
        })
        result = _build_folder_path(service, ["folder2"], {})
        assert result == "My Drive/Projects"

    def test_three_levels(self):
        service = _MockService({
            "f3": {"name": "Docs", "parents": ["f2"]},
            "f2": {"name": "Work", "parents": ["f1"]},
            "f1": {"name": "My Drive", "parents": []},
        })
        result = _build_folder_path(service, ["f3"], {})
        assert result == "My Drive/Work/Docs"

    def test_cache_prevents_redundant_lookups(self):
        service = _MockService({
            "f2": {"name": "Projects", "parents": ["f1"]},
            "f1": {"name": "My Drive", "parents": []},
        })
        cache = {}

        # First call populates cache
        result1 = _build_folder_path(service, ["f2"], cache)
        assert result1 == "My Drive/Projects"
        assert "f1" in cache
        assert "f2" in cache

        # Second call for same parent uses cache (no API call)
        result2 = _build_folder_path(service, ["f2"], cache)
        assert result2 == "Projects"  # Cache hit on f2 returns just the name

    def test_cache_hit_on_parent(self):
        """When the parent folder is already cached, we stop traversing."""
        cache = {"f1": "Root"}
        service = _MockService({
            "f2": {"name": "Sub", "parents": ["f1"]},
        })
        result = _build_folder_path(service, ["f2"], cache)
        assert result == "Root/Sub"

    def test_uses_first_parent_only(self):
        """Drive files nominally have at most one parent, but the API returns a list."""
        service = _MockService({
            "parent1": {"name": "Primary", "parents": []},
            "parent2": {"name": "Secondary", "parents": []},
        })
        result = _build_folder_path(service, ["parent1", "parent2"], {})
        assert result == "Primary"


# --- Edge cases and constants ---


class TestConstants:
    def test_max_download_bytes_reasonable(self):
        assert MAX_DOWNLOAD_BYTES == 5 * 1024 * 1024

    def test_text_mime_prefixes_are_tuples(self):
        """Ensure TEXT_MIME_PREFIXES is a tuple (required for str.startswith)."""
        assert isinstance(TEXT_MIME_PREFIXES, tuple)

    def test_drive_scopes_present(self):
        from src.ingestion.drive import DRIVE_SCOPES
        assert len(DRIVE_SCOPES) >= 1
        assert any("drive" in s for s in DRIVE_SCOPES)
