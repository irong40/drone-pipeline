"""
Integration test: full ingest flow — SD card scan -> sequence sorting ->
mission folder creation -> file copy -> inventory count. INTG-01.

Real filesystem I/O against tmp_path, no mocking.
"""
import os
import pytest

pytest.importorskip("requests", reason="requests required for ingest_sorter")

from ingest_sorter import (
    scan_sd_card,
    sort_by_sequence_ranges,
    build_mission_folder_name,
    create_mission_structure,
    copy_file_to_mission,
    count_inventory,
)


@pytest.fixture
def sd_card_root(tmp_path):
    """Synthetic SD card with DJI files spanning sequences 1-5 plus one outlier."""
    sd = tmp_path / "sdcard"
    sd.mkdir()

    # Seq 1-5: assigned to mission
    (sd / "DJI_0001.JPG").write_bytes(b"\xff\xd8jpg1")
    (sd / "DJI_0002.DNG").write_bytes(b"\x00dng2")
    (sd / "DJI_0003.MP4").write_bytes(b"\x00\x00mp4_3")
    (sd / "DJI_0004.SRT").write_bytes(b"srt4")
    (sd / "DJI_0005.MRK").write_bytes(b"mrk5")

    # Seq 20: outside range — unassigned
    (sd / "DJI_0020.JPG").write_bytes(b"\xff\xd8jpg20")

    # Non-DJI file — should be skipped by scanner
    (sd / "non_dji.txt").write_bytes(b"skip me")

    return sd


@pytest.fixture
def missions_config():
    """Single mission covering sequences 1-10."""
    return [
        {
            "mission_id": "test-mission-uuid",
            "mission_number": 47,
            "package_type": "re_standard",
            "date": "20260218",
            "sequence_start": 1,
            "sequence_end": 10,
        }
    ]


def test_full_ingest_sorts_files_into_mission_subfolders(sd_card_root, missions_config, tmp_path):
    """Full flow: scan -> sort -> create structure -> copy -> verify on disk."""
    files = scan_sd_card(str(sd_card_root))
    assert len(files) == 6  # 5 assigned + 1 outlier (DJI_0020)

    sorted_missions, unassigned = sort_by_sequence_ranges(files, missions_config)
    assert len(unassigned) == 1
    assert unassigned[0]["sequence"] == 20

    mid = missions_config[0]["mission_id"]
    assert mid in sorted_missions
    assert len(sorted_missions[mid]) == 5

    # Create folder and copy
    folder_name = build_mission_folder_name(missions_config[0])
    incoming = tmp_path / "incoming"
    mission_path = create_mission_structure(folder_name, root=str(incoming))

    # Verify all 6 standard subfolders exist
    for subfolder in ["photos/raw", "photos/jpeg", "video/full", "video/proxy", "video/telemetry", "ppk"]:
        assert os.path.isdir(os.path.join(mission_path, subfolder))

    # Copy assigned files
    for f in sorted_missions[mid]:
        dest = copy_file_to_mission(f, mission_path)
        assert dest is not None
        assert os.path.isfile(dest)


def test_ingest_unassigned_files_not_copied(sd_card_root, tmp_path):
    """Outlier (seq 20) is not assigned to any mission."""
    # Config covers only seq 100-200 — nothing matches
    config = [{
        "mission_id": "empty-mission",
        "mission_number": 99,
        "package_type": "re_standard",
        "date": "20260218",
        "sequence_start": 100,
        "sequence_end": 200,
    }]

    files = scan_sd_card(str(sd_card_root))
    sorted_missions, unassigned = sort_by_sequence_ranges(files, config)
    assert sorted_missions.get("empty-mission", []) == []
    assert len(unassigned) == 6  # All files unassigned


def test_ingest_multi_extension_routing(sd_card_root, missions_config, tmp_path):
    """Each file type routes to the correct subfolder."""
    files = scan_sd_card(str(sd_card_root))
    sorted_missions, _ = sort_by_sequence_ranges(files, missions_config)
    mid = missions_config[0]["mission_id"]

    folder_name = build_mission_folder_name(missions_config[0])
    incoming = tmp_path / "incoming"
    mission_path = create_mission_structure(folder_name, root=str(incoming))

    for f in sorted_missions[mid]:
        copy_file_to_mission(f, mission_path)

    # Verify routing
    assert os.path.isfile(os.path.join(mission_path, "photos", "jpeg", "DJI_0001.JPG"))
    assert os.path.isfile(os.path.join(mission_path, "photos", "raw", "DJI_0002.DNG"))
    assert os.path.isfile(os.path.join(mission_path, "video", "full", "DJI_0003.MP4"))
    assert os.path.isfile(os.path.join(mission_path, "video", "telemetry", "DJI_0004.SRT"))
    assert os.path.isfile(os.path.join(mission_path, "ppk", "DJI_0005.MRK"))


def test_inventory_count_after_ingest(sd_card_root, missions_config, tmp_path):
    """count_inventory reflects actual copied files."""
    files = scan_sd_card(str(sd_card_root))
    sorted_missions, _ = sort_by_sequence_ranges(files, missions_config)
    mid = missions_config[0]["mission_id"]

    folder_name = build_mission_folder_name(missions_config[0])
    incoming = tmp_path / "incoming"
    mission_path = create_mission_structure(folder_name, root=str(incoming))

    for f in sorted_missions[mid]:
        copy_file_to_mission(f, mission_path)

    inventory = count_inventory(mission_path)
    assert inventory["photo_count"] == 2  # 1 JPG + 1 DNG
    assert inventory["video_count"] == 1  # 1 MP4
    assert inventory["has_ppk_data"] is True  # 1 MRK
