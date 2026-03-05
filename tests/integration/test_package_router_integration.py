"""
Package Router integration tests (TST-04).

Tests the webhook-to-Supabase processing_jobs flow:
- Ingest_sorter and folder_watcher payload normalization
- Processing step generation per package_type
- Job creation with correct structure in processing_jobs table
- Manual path routing for construction_hybrid, adiat, and unknown types
"""
import sys
import os

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from payload_normalizer import normalize_payload


# ---------------------------------------------------------------------------
# Test utilities — simulate Package Router behavior
# ---------------------------------------------------------------------------

def build_processing_steps(package_type: str) -> list[dict]:
    """
    Return the expected processing steps array for a given package type.

    Mirrors what the n8n Package Router would create as the steps array
    in a processing_jobs row.
    """
    STEP_MAP = {
        "re_standard": [
            {"name": "color_grade", "status": "pending"},
            {"name": "delivery_packaging", "status": "pending"},
        ],
        "real_estate": [
            {"name": "color_grade", "status": "pending"},
            {"name": "delivery_packaging", "status": "pending"},
        ],
        "mapping": [
            {"name": "mipmap_launch", "status": "pending"},
            {"name": "ortho_harvest", "status": "pending"},
            {"name": "delivery_packaging", "status": "pending"},
        ],
        "site_survey": [
            {"name": "mipmap_launch", "status": "pending"},
            {"name": "ortho_harvest", "status": "pending"},
            {"name": "delivery_packaging", "status": "pending"},
        ],
        "environmental_survey": [
            {"name": "mipmap_launch", "status": "pending"},
            {"name": "ortho_harvest", "status": "pending"},
            {"name": "delivery_packaging", "status": "pending"},
        ],
        "video": [
            {"name": "v1_color", "status": "pending"},
            {"name": "v1_5_metadata", "status": "pending"},
            {"name": "v2_srt", "status": "pending"},
            {"name": "v3_qa", "status": "pending"},
            {"name": "v4_proxy", "status": "pending"},
            {"name": "v5_resolve_gate", "status": "pending"},
            {"name": "v6_export", "status": "pending"},
            {"name": "delivery_packaging", "status": "pending"},
        ],
        "construction_hybrid": [],  # Manual handling
        "adiat": [],  # Manual handling
    }
    return STEP_MAP.get(package_type, [])  # Unknown -> empty (manual)


def simulate_router_job_creation(normalized_payload: dict, supabase_client) -> dict:
    """
    Simulate the Package Router creating a processing_jobs row.

    Takes a normalized payload and mock Supabase client, builds the steps
    array, and inserts a processing_jobs row.
    """
    package_type = normalized_payload["package_type"]
    steps = build_processing_steps(package_type)

    # Determine status based on whether there are automated steps
    status = "queued" if steps else "manual"

    job_row = {
        "mission_id": normalized_payload["mission_id"],
        "package_type": package_type,
        "status": status,
        "steps": steps,
        "source": normalized_payload.get("source", "unknown"),
    }

    result = supabase_client.table("processing_jobs").insert(job_row).execute()
    return {**job_row, "id": result.data[0]["id"]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPackageRouterIntegration:
    """Integration tests for the Package Router webhook-to-Supabase flow."""

    def test_ingest_sorter_payload_creates_processing_job(self, mock_supabase_client):
        """Ingest_sorter payload normalizes and creates a processing_jobs row."""
        raw_payload = {
            "mission_id": "mission-uuid-001",
            "mission_number": 47,
            "package_type": "re_standard",
            "photo_count": 120,
            "video_count": 0,
            "has_ppk_data": True,
            "sorted_folder": "D:/Incoming/SAI_M0047_re_standard_20260218",
        }

        normalized = normalize_payload(raw_payload)

        assert normalized["mission_id"] == "mission-uuid-001"
        assert normalized["package_type"] == "re_standard"
        assert normalized["source"] == "ingest_sorter"
        assert normalized["needs_mission_lookup"] is False

        job = simulate_router_job_creation(normalized, mock_supabase_client)

        assert job["mission_id"] == "mission-uuid-001"
        assert job["package_type"] == "re_standard"
        assert job["status"] == "queued"
        assert len(job["steps"]) == 2
        assert job["steps"][0]["name"] == "color_grade"
        assert job["steps"][1]["name"] == "delivery_packaging"

        # Verify Supabase insert was called
        mock_supabase_client.table.assert_called_with("processing_jobs")
        mock_supabase_client.table("processing_jobs").insert.assert_called_once()

    def test_folder_watcher_payload_normalizes_correctly(self):
        """Folder_watcher payload parses package_type from folder_name."""
        raw_payload = {
            "folder_name": "SAI_M0047_re_standard_20260218",
            "folder_path": "D:/Incoming/SAI_M0047_re_standard_20260218",
            "photo_count": 120,
        }

        normalized = normalize_payload(raw_payload)

        assert normalized["source"] == "folder_watcher"
        assert normalized["needs_mission_lookup"] is True
        assert normalized["package_type"] == "re_standard"
        assert normalized["mission_number"] == 47
        assert normalized["mission_id"] is None
        assert normalized["is_fallback"] is True

    @pytest.mark.parametrize(
        "package_type,expected_step_names",
        [
            ("re_standard", ["color_grade", "delivery_packaging"]),
            ("real_estate", ["color_grade", "delivery_packaging"]),
            ("mapping", ["mipmap_launch", "ortho_harvest", "delivery_packaging"]),
            ("site_survey", ["mipmap_launch", "ortho_harvest", "delivery_packaging"]),
            (
                "environmental_survey",
                ["mipmap_launch", "ortho_harvest", "delivery_packaging"],
            ),
            (
                "video",
                [
                    "v1_color",
                    "v1_5_metadata",
                    "v2_srt",
                    "v3_qa",
                    "v4_proxy",
                    "v5_resolve_gate",
                    "v6_export",
                    "delivery_packaging",
                ],
            ),
        ],
        ids=[
            "re_standard",
            "real_estate",
            "mapping",
            "site_survey",
            "environmental_survey",
            "video",
        ],
    )
    def test_processing_steps_for_each_package_type(
        self, package_type, expected_step_names
    ):
        """Each automated package_type produces the correct steps array."""
        steps = build_processing_steps(package_type)

        assert len(steps) == len(expected_step_names)
        actual_names = [s["name"] for s in steps]
        assert actual_names == expected_step_names

        # Every step starts as pending
        for step in steps:
            assert step["status"] == "pending"

    @pytest.mark.parametrize(
        "package_type",
        ["construction_hybrid", "adiat"],
        ids=["construction_hybrid", "adiat"],
    )
    def test_manual_path_creates_empty_steps(self, mock_supabase_client, package_type):
        """Construction_hybrid and adiat produce empty steps with manual status."""
        normalized = {
            "mission_id": "mission-uuid-manual",
            "package_type": package_type,
            "source": "ingest_sorter",
        }

        job = simulate_router_job_creation(normalized, mock_supabase_client)

        assert job["steps"] == []
        assert job["status"] == "manual"
        assert job["package_type"] == package_type

    def test_unknown_package_type_routes_to_manual(self, mock_supabase_client):
        """Unknown package_type gets empty steps and manual status."""
        normalized = {
            "mission_id": "mission-uuid-unknown",
            "package_type": "some_new_type_never_seen",
            "source": "folder_watcher",
        }

        job = simulate_router_job_creation(normalized, mock_supabase_client)

        assert job["steps"] == []
        assert job["status"] == "manual"
