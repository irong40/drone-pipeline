"""
Unit tests for ortho_harvester.py -- GeoTIFF copy utility with integrity verification.
MPC-04, MPC-05, TST-02.
"""
import os
import json
import types
import sys
import pytest
from unittest.mock import MagicMock, patch, call


# ── Supabase sys.modules stub (supabase not installed in CI) ──────────────────

@pytest.fixture(autouse=True)
def stub_supabase_module(mocker):
    """Inject fake 'supabase' module so imports work without the real package."""
    if "supabase" not in sys.modules:
        fake_supabase = types.ModuleType("supabase")
        fake_supabase.create_client = MagicMock()
        mocker.patch.dict(sys.modules, {"supabase": fake_supabase})


# ── Rasterio sys.modules stub (rasterio may not be installed) ────────────────

class MockRasterioDataset:
    """Configurable mock rasterio dataset used as context manager."""

    def __init__(self, width=1024, height=1024, count=4, crs="EPSG:4326", raise_on_read=False):
        self.width = width
        self.height = height
        self.count = count
        self.crs = crs
        self._raise_on_read = raise_on_read

    def read(self, band, window=None):
        if self._raise_on_read:
            raise Exception("Read error")
        return [[0]]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture(autouse=True)
def stub_rasterio_module(mocker):
    """Inject fake 'rasterio' module so imports work without the real package."""
    fake_rasterio = types.ModuleType("rasterio")
    # Default: valid dataset
    fake_rasterio.open = MagicMock(return_value=MockRasterioDataset())
    mocker.patch.dict(sys.modules, {"rasterio": fake_rasterio})
    return fake_rasterio


# ── validate_geotiff ─────────────────────────────────────────────────────────

def test_validate_geotiff_valid(stub_rasterio_module):
    stub_rasterio_module.open = MagicMock(
        return_value=MockRasterioDataset(width=1024, height=1024, count=4, crs="EPSG:4326")
    )
    from ortho_harvester import validate_geotiff
    valid, info = validate_geotiff("/fake/ortho.tif")
    assert valid is True
    assert "1024" in info


def test_validate_geotiff_no_crs(stub_rasterio_module):
    stub_rasterio_module.open = MagicMock(
        return_value=MockRasterioDataset(crs=None)
    )
    from ortho_harvester import validate_geotiff
    valid, info = validate_geotiff("/fake/ortho.tif")
    assert valid is False
    assert "CRS" in info or "crs" in info.lower()


def test_validate_geotiff_zero_dimensions(stub_rasterio_module):
    stub_rasterio_module.open = MagicMock(
        return_value=MockRasterioDataset(width=0, height=0)
    )
    from ortho_harvester import validate_geotiff
    valid, info = validate_geotiff("/fake/ortho.tif")
    assert valid is False
    assert "dimension" in info.lower() or "zero" in info.lower()


def test_validate_geotiff_no_bands(stub_rasterio_module):
    stub_rasterio_module.open = MagicMock(
        return_value=MockRasterioDataset(count=0)
    )
    from ortho_harvester import validate_geotiff
    valid, info = validate_geotiff("/fake/ortho.tif")
    assert valid is False
    assert "band" in info.lower()


def test_validate_geotiff_corrupt(stub_rasterio_module):
    stub_rasterio_module.open = MagicMock(side_effect=Exception("Corrupt file"))
    from ortho_harvester import validate_geotiff
    valid, info = validate_geotiff("/fake/ortho.tif")
    assert valid is False
    assert "Corrupt" in info or "error" in info.lower()


# ── verify_copy_integrity ────────────────────────────────────────────────────

def test_verify_copy_integrity_size_mismatch(stub_rasterio_module, mocker):
    mocker.patch("os.path.getsize", side_effect=[1000, 500])
    from ortho_harvester import verify_copy_integrity
    valid, info = verify_copy_integrity("/src/ortho.tif", "/dst/ortho.tif")
    assert valid is False
    assert "size" in info.lower() or "mismatch" in info.lower()


def test_verify_copy_integrity_valid(stub_rasterio_module, mocker):
    mocker.patch("os.path.getsize", return_value=1000)
    stub_rasterio_module.open = MagicMock(
        return_value=MockRasterioDataset()
    )
    from ortho_harvester import verify_copy_integrity
    valid, info = verify_copy_integrity("/src/ortho.tif", "/dst/ortho.tif")
    assert valid is True


# ── copy_ortho ───────────────────────────────────────────────────────────────

def test_copy_ortho_creates_mapping_dir(tmp_path, mocker):
    source = tmp_path / "workspace" / "ortho.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake tiff data")
    mission = tmp_path / "mission"
    mission.mkdir()

    mocker.patch("shutil.copy2")
    mocker.patch("os.rename")

    from ortho_harvester import copy_ortho
    copy_ortho(str(source), str(mission))

    mapping_dir = mission / "mapping"
    assert mapping_dir.is_dir()


def test_copy_ortho_uses_temp_then_rename(tmp_path, mocker):
    source = tmp_path / "workspace" / "ortho.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake tiff data")
    mission = tmp_path / "mission"
    mission.mkdir()

    mock_copy = mocker.patch("shutil.copy2")
    mock_rename = mocker.patch("os.rename")

    from ortho_harvester import copy_ortho
    copy_ortho(str(source), str(mission))

    # Should copy to .tmp first
    copy_call_dest = mock_copy.call_args[0][1]
    assert copy_call_dest.endswith(".tmp")

    # Then rename .tmp to final
    rename_src = mock_rename.call_args[0][0]
    rename_dst = mock_rename.call_args[0][1]
    assert rename_src.endswith(".tmp")
    assert not rename_dst.endswith(".tmp")


def test_copy_ortho_returns_dest_path(tmp_path, mocker):
    source = tmp_path / "workspace" / "ortho.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake tiff data")
    mission = tmp_path / "mission"
    mission.mkdir()

    mocker.patch("shutil.copy2")
    mocker.patch("os.rename")

    from ortho_harvester import copy_ortho
    result = copy_ortho(str(source), str(mission))

    assert result.endswith("ortho.tif")
    assert "mapping" in result


# ── main() exit codes and pipeline contract ──────────────────────────────────

def test_main_exit_0_on_success(tmp_path, mocker, stub_rasterio_module):
    source = tmp_path / "workspace" / "ortho.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake tiff data")
    mission = tmp_path / "mission"
    mission.mkdir()

    mocker.patch("shutil.copy2")
    mocker.patch("os.rename")
    mocker.patch("os.path.getsize", return_value=1000)
    stub_rasterio_module.open = MagicMock(return_value=MockRasterioDataset())
    mocker.patch("pipeline_utils.setup_logging", return_value=MagicMock())
    mocker.patch("pipeline_utils.LOG_DIR", str(tmp_path / "logs"))

    from ortho_harvester import main
    mocker.patch("sys.argv", [
        "ortho_harvester.py",
        "--source-path", str(source),
        "--mission-path", str(mission),
        "--mission-id", "test-uuid",
    ])

    # Should not raise SystemExit or exit with 0
    main()


def test_main_exit_1_on_copy_failure(tmp_path, mocker, stub_rasterio_module):
    source = tmp_path / "workspace" / "ortho.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake tiff data")
    mission = tmp_path / "mission"
    mission.mkdir()

    mocker.patch("shutil.copy2", side_effect=OSError("Disk full"))
    mocker.patch("pipeline_utils.setup_logging", return_value=MagicMock())
    mocker.patch("pipeline_utils.LOG_DIR", str(tmp_path / "logs"))

    from ortho_harvester import main
    mocker.patch("sys.argv", [
        "ortho_harvester.py",
        "--source-path", str(source),
        "--mission-path", str(mission),
        "--mission-id", "test-uuid",
    ])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_exit_2_missing_source(tmp_path, mocker):
    mission = tmp_path / "mission"
    mission.mkdir()

    mocker.patch("pipeline_utils.setup_logging", return_value=MagicMock())
    mocker.patch("pipeline_utils.LOG_DIR", str(tmp_path / "logs"))

    from ortho_harvester import main
    mocker.patch("sys.argv", [
        "ortho_harvester.py",
        "--source-path", str(tmp_path / "nonexistent.tif"),
        "--mission-path", str(mission),
        "--mission-id", "test-uuid",
    ])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2


def test_main_prints_json_stdout(tmp_path, mocker, stub_rasterio_module, capsys):
    source = tmp_path / "workspace" / "ortho.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake tiff data")
    mission = tmp_path / "mission"
    mission.mkdir()

    mocker.patch("shutil.copy2")
    mocker.patch("os.rename")
    mocker.patch("os.path.getsize", return_value=1000)
    stub_rasterio_module.open = MagicMock(return_value=MockRasterioDataset())
    mocker.patch("pipeline_utils.setup_logging", return_value=MagicMock())
    mocker.patch("pipeline_utils.LOG_DIR", str(tmp_path / "logs"))

    from ortho_harvester import main
    mocker.patch("sys.argv", [
        "ortho_harvester.py",
        "--source-path", str(source),
        "--mission-path", str(mission),
        "--mission-id", "test-uuid",
    ])

    main()
    captured = capsys.readouterr()
    # Last non-empty line should be valid JSON
    lines = [l for l in captured.out.strip().split("\n") if l.strip()]
    assert len(lines) >= 1
    result = json.loads(lines[-1])
    assert "status" in result


def test_main_uses_pipeline_contract(tmp_path, mocker, stub_rasterio_module):
    source = tmp_path / "workspace" / "ortho.tif"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake tiff data")
    mission = tmp_path / "mission"
    mission.mkdir()

    mocker.patch("shutil.copy2")
    mocker.patch("os.rename")
    mocker.patch("os.path.getsize", return_value=1000)
    stub_rasterio_module.open = MagicMock(return_value=MockRasterioDataset())
    mock_log = MagicMock()
    mocker.patch("pipeline_utils.setup_logging", return_value=mock_log)
    mocker.patch("pipeline_utils.LOG_DIR", str(tmp_path / "logs"))

    mock_reporter = MagicMock()
    mocker.patch("ortho_harvester.PipelineStatusReporter", return_value=mock_reporter)

    from ortho_harvester import main
    mocker.patch("sys.argv", [
        "ortho_harvester.py",
        "--source-path", str(source),
        "--mission-path", str(mission),
        "--mission-id", "test-uuid",
    ])

    main()

    # Pipeline contract: start() and complete() called
    mock_reporter.start.assert_called_once()
    mock_reporter.complete.assert_called_once()
