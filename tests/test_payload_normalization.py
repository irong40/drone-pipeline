"""
Tests for payload_normalizer.py — pure function tests for folder name parsing
and payload normalization logic.

Mirrors the JavaScript Code node logic (package_router_normalizer.js) to ensure
correctness of the Python reference implementation.
"""
import pytest
import sys
import os

# Add scripts/ to path so we can import payload_normalizer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from payload_normalizer import parse_folder_name, normalize_payload


# ── parse_folder_name tests ──────────────────────────────────────────────────


class TestParseFolderName:
    """Tests for parse_folder_name()."""

    def test_standard_real_estate(self):
        result = parse_folder_name("SAI_M0047_re_standard_20260218")
        assert result is not None
        assert result["mission_number"] == 47
        assert result["package_type"] == "re_standard"
        assert result["date"] == "20260218"

    def test_construction_hybrid_with_underscore(self):
        """Package type with underscore (construction_hybrid) is captured correctly."""
        result = parse_folder_name("SAI_M0001_construction_hybrid_20260301")
        assert result is not None
        assert result["mission_number"] == 1
        assert result["package_type"] == "construction_hybrid"
        assert result["date"] == "20260301"

    def test_site_survey(self):
        result = parse_folder_name("SAI_M0123_site_survey_20260415")
        assert result is not None
        assert result["mission_number"] == 123
        assert result["package_type"] == "site_survey"

    def test_environmental_survey(self):
        result = parse_folder_name("SAI_M0005_environmental_survey_20260501")
        assert result is not None
        assert result["mission_number"] == 5
        assert result["package_type"] == "environmental_survey"

    def test_video(self):
        result = parse_folder_name("SAI_M0200_video_20260601")
        assert result is not None
        assert result["mission_number"] == 200
        assert result["package_type"] == "video"

    def test_mapping(self):
        result = parse_folder_name("SAI_M0099_mapping_20260701")
        assert result is not None
        assert result["mission_number"] == 99
        assert result["package_type"] == "mapping"

    def test_invalid_random_folder(self):
        result = parse_folder_name("random_folder")
        assert result is None

    def test_invalid_no_prefix(self):
        result = parse_folder_name("M0047_re_standard_20260218")
        assert result is None

    def test_invalid_empty_string(self):
        result = parse_folder_name("")
        assert result is None

    def test_invalid_no_date(self):
        result = parse_folder_name("SAI_M0047_re_standard")
        assert result is None

    def test_mission_number_leading_zeros(self):
        """Mission number 0001 should parse to integer 1."""
        result = parse_folder_name("SAI_M0001_video_20260101")
        assert result is not None
        assert result["mission_number"] == 1
        assert isinstance(result["mission_number"], int)


# ── normalize_payload tests ──────────────────────────────────────────────────


class TestNormalizePayloadIngestSorter:
    """Tests for normalize_payload() with ingest_sorter payloads."""

    @pytest.fixture
    def ingest_payload(self):
        return {
            "mission_id": "uuid-from-supabase",
            "mission_number": 47,
            "package_type": "re_standard",
            "photo_count": 24,
            "video_count": 0,
            "has_ppk_data": True,
            "source_platform": "mini4pro",
            "ingested_at": "2026-02-18T12:00:00Z",
        }

    def test_source_is_ingest_sorter(self, ingest_payload):
        result = normalize_payload(ingest_payload)
        assert result["source"] == "ingest_sorter"

    def test_no_mission_lookup_needed(self, ingest_payload):
        result = normalize_payload(ingest_payload)
        assert result["needs_mission_lookup"] is False

    def test_mission_id_preserved(self, ingest_payload):
        result = normalize_payload(ingest_payload)
        assert result["mission_id"] == "uuid-from-supabase"

    def test_all_fields_present(self, ingest_payload):
        result = normalize_payload(ingest_payload)
        assert result["mission_number"] == 47
        assert result["package_type"] == "re_standard"
        assert result["photo_count"] == 24
        assert result["video_count"] == 0
        assert result["has_ppk_data"] is True

    def test_is_fallback_false(self, ingest_payload):
        result = normalize_payload(ingest_payload)
        assert result["is_fallback"] is False


class TestNormalizePayloadFolderWatcher:
    """Tests for normalize_payload() with folder_watcher payloads."""

    @pytest.fixture
    def folder_payload(self):
        return {
            "folder_path": "E:\\Sentinel\\Incoming\\SAI_M0047_re_standard_20260218",
            "folder_name": "SAI_M0047_re_standard_20260218",
            "mission_number": 47,
            "photo_count": 24,
            "video_count": 0,
            "has_ppk_data": True,
            "total_size_bytes": 1048576,
            "detected_at": "2026-02-18T12:00:00Z",
        }

    def test_source_is_folder_watcher(self, folder_payload):
        result = normalize_payload(folder_payload)
        assert result["source"] == "folder_watcher"

    def test_needs_mission_lookup(self, folder_payload):
        result = normalize_payload(folder_payload)
        assert result["needs_mission_lookup"] is True

    def test_package_type_parsed_from_folder_name(self, folder_payload):
        result = normalize_payload(folder_payload)
        assert result["package_type"] == "re_standard"

    def test_mission_number_parsed(self, folder_payload):
        result = normalize_payload(folder_payload)
        assert result["mission_number"] == 47

    def test_folder_path_preserved(self, folder_payload):
        result = normalize_payload(folder_payload)
        assert result["folder_path"] == "E:\\Sentinel\\Incoming\\SAI_M0047_re_standard_20260218"

    def test_is_fallback_true(self, folder_payload):
        result = normalize_payload(folder_payload)
        assert result["is_fallback"] is True

    def test_unknown_folder_name(self):
        payload = {
            "folder_path": "E:\\Sentinel\\Incoming\\random_folder",
            "folder_name": "random_folder",
            "mission_number": 0,
            "photo_count": 10,
            "video_count": 0,
            "has_ppk_data": False,
            "total_size_bytes": 500000,
            "detected_at": "2026-02-18T12:00:00Z",
        }
        result = normalize_payload(payload)
        assert result["package_type"] == "unknown"
        assert result["source"] == "folder_watcher"
        assert result["needs_mission_lookup"] is True
