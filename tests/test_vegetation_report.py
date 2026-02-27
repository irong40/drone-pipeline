"""
Unit tests for vegetation_report.py — species map, health map, GeoJSON,
Folium interactive map, PDF generation, Supabase summary write. TST-04.
"""
import os
import sys
import json
import types
import tempfile
import logging
import pytest
from unittest.mock import MagicMock, patch


# ── Module-level stubs ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def stub_supabase_module(mocker):
    """Inject a fake supabase module so tests work without the real package."""
    if "supabase" not in sys.modules:
        fake_sb = types.ModuleType("supabase")
        fake_sb.create_client = MagicMock()
        mocker.patch.dict(sys.modules, {"supabase": fake_sb})


# ── Test data helpers ─────────────────────────────────────────────────────────

def _make_detection(
    index=0,
    species="Live Oak",
    health_score=0.8,
    health_status="healthy",
    wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
    area=25.0,
    conf=0.85,
    lat=36.85,
    lon=-76.29,
):
    """Return a minimal detection dict for testing."""
    return {
        "id": f"det-{index}",
        "detection_index": index,
        "species_tag": species,
        "species_confidence": conf,
        "health_score": health_score,
        "health_status": health_status,
        "geometry_wkt": wkt,
        "centroid_lat": lat,
        "centroid_lon": lon,
        "canopy_area_sqm": area,
        "detection_confidence": 0.90,
        "recommended_action": None,
        "health_details": None,
    }


def _make_mock_rasterio_dataset():
    """Return a mock rasterio dataset with common attributes."""
    import numpy as np
    from unittest.mock import MagicMock

    ds = MagicMock()
    ds.__enter__ = MagicMock(return_value=ds)
    ds.__exit__ = MagicMock(return_value=False)
    ds.count = 3
    ds.width = 100
    ds.height = 100
    ds.crs = MagicMock()
    ds.crs.to_epsg = MagicMock(return_value=4326)
    ds.crs.is_geographic = True
    ds.bounds = MagicMock()
    ds.bounds.left = -76.30
    ds.bounds.bottom = 36.84
    ds.bounds.right = -76.28
    ds.bounds.top = 36.86
    ds.transform = MagicMock()
    ds.transform.a = 0.0001
    ds.transform.e = -0.0001

    # read() returns (3, 100, 100) uint8 array
    rgb = np.random.randint(50, 200, (3, 100, 100), dtype=np.uint8)
    ds.read = MagicMock(return_value=rgb)
    return ds


# ── Species map PNG ───────────────────────────────────────────────────────────

class TestSpeciesMapPng:
    """test_species_map_png — Generated PNG exists and is non-empty."""

    def test_species_map_creates_file(self, tmp_path):
        """generate_species_map() creates a PNG file at the specified path."""
        import numpy as np
        from vegetation_report import generate_species_map

        detections = [
            _make_detection(0, "Live Oak", wkt="POLYGON ((0.0001 0.0001, 0.0002 0.0001, 0.0002 0.0002, 0.0001 0.0002, 0.0001 0.0001))"),
        ]
        output_path = str(tmp_path / "test_species_map.png")
        mock_ds = _make_mock_rasterio_dataset()

        with patch("vegetation_report.rasterio.open") as mock_open, \
             patch("vegetation_report.rasterio.plot.show"), \
             patch("vegetation_report.plt.subplots") as mock_subplots:

            mock_open.return_value = mock_ds
            fig_mock = MagicMock()
            ax_mock = MagicMock()
            mock_subplots.return_value = (fig_mock, ax_mock)

            # Make savefig create an actual file
            def fake_savefig(path, **kwargs):
                with open(path, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

            fig_mock.savefig.side_effect = fake_savefig

            result = generate_species_map(
                ortho_path="fake.tif",
                detections=detections,
                output_path=output_path,
            )

        assert result is True
        assert os.path.isfile(output_path)
        assert os.path.getsize(output_path) > 0

    def test_species_map_returns_false_on_error(self, tmp_path):
        """generate_species_map() returns False when rasterio.open fails."""
        from vegetation_report import generate_species_map

        output_path = str(tmp_path / "species.png")
        with patch("vegetation_report.rasterio.open", side_effect=RuntimeError("read error")):
            result = generate_species_map(
                ortho_path="nonexistent.tif",
                detections=[],
                output_path=output_path,
            )
        assert result is False


# ── Health map PNG ────────────────────────────────────────────────────────────

class TestHealthMapPng:
    """test_health_map_png — Generated PNG with correct color mapping."""

    def test_health_map_creates_file(self, tmp_path):
        """generate_health_map() creates a PNG at the specified path."""
        from vegetation_report import generate_health_map

        detections = [
            _make_detection(0, health_status="healthy"),
            _make_detection(1, health_status="stressed"),
        ]
        output_path = str(tmp_path / "health_map.png")
        mock_ds = _make_mock_rasterio_dataset()

        with patch("vegetation_report.rasterio.open") as mock_open, \
             patch("vegetation_report.rasterio.plot.show"), \
             patch("vegetation_report.plt.subplots") as mock_subplots:

            mock_open.return_value = mock_ds
            fig_mock = MagicMock()
            ax_mock = MagicMock()
            mock_subplots.return_value = (fig_mock, ax_mock)

            def fake_savefig(path, **kwargs):
                with open(path, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

            fig_mock.savefig.side_effect = fake_savefig

            result = generate_health_map(
                ortho_path="fake.tif",
                detections=detections,
                output_path=output_path,
            )

        assert result is True
        assert os.path.isfile(output_path)
        assert os.path.getsize(output_path) > 0

    def test_health_map_uses_health_colors(self):
        """HEALTH_COLORS contains correct color codes for all health statuses."""
        from vegetation_report import HEALTH_COLORS

        expected = {
            "healthy": "#22C55E",
            "moderate_stress": "#EAB308",
            "stressed": "#F97316",
            "severe_decline": "#EF4444",
            "dead": "#000000",
        }
        for status, color in expected.items():
            assert HEALTH_COLORS[status] == color, (
                f"HEALTH_COLORS[{status!r}] = {HEALTH_COLORS[status]!r}, expected {color!r}"
            )

    def test_health_map_returns_false_on_error(self, tmp_path):
        """generate_health_map() returns False when rasterio.open fails."""
        from vegetation_report import generate_health_map

        output_path = str(tmp_path / "health.png")
        with patch("vegetation_report.rasterio.open", side_effect=RuntimeError("read error")):
            result = generate_health_map(
                ortho_path="nonexistent.tif",
                detections=[],
                output_path=output_path,
            )
        assert result is False


# ── GeoJSON valid ─────────────────────────────────────────────────────────────

class TestGeojsonValid:
    """test_geojson_valid — Output GeoJSON parseable with required properties."""

    def test_geojson_parses_and_has_features(self, tmp_path):
        """export_geojson() writes valid GeoJSON with features for all detections."""
        from vegetation_report import export_geojson

        detections = [
            _make_detection(0, "Live Oak"),
            _make_detection(1, "Red Maple"),
        ]
        output_path = str(tmp_path / "test.geojson")

        result = export_geojson(
            detections=detections,
            output_path=output_path,
        )

        assert result is True
        assert os.path.isfile(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            gj = json.load(f)

        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == 2

    def test_geojson_has_required_properties(self, tmp_path):
        """Each GeoJSON feature has detection_index, species_tag, health_score, health_status."""
        from vegetation_report import export_geojson

        detections = [_make_detection(0, "Loblolly Pine", health_score=0.7, health_status="moderate_stress")]
        output_path = str(tmp_path / "test.geojson")

        export_geojson(detections=detections, output_path=output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            gj = json.load(f)

        feature = gj["features"][0]
        props = feature["properties"]
        required_keys = [
            "detection_index", "species_tag", "health_score",
            "health_status", "canopy_area_sqm", "recommended_action",
        ]
        for key in required_keys:
            assert key in props, f"GeoJSON feature missing property: {key}"

    def test_geojson_empty_detections_writes_empty_collection(self, tmp_path):
        """export_geojson() with no detections writes empty FeatureCollection."""
        from vegetation_report import export_geojson

        output_path = str(tmp_path / "empty.geojson")
        result = export_geojson(detections=[], output_path=output_path)

        assert result is True
        with open(output_path, "r", encoding="utf-8") as f:
            gj = json.load(f)
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == 0


# ── GeoJSON CRS ───────────────────────────────────────────────────────────────

class TestGeojsonCrs:
    """test_geojson_crs — CRS is EPSG:4326."""

    def test_geojson_geometry_is_wgs84_compatible(self, tmp_path):
        """Coordinate values in GeoJSON are in WGS84 degree range [-180,180] x [-90,90]."""
        from vegetation_report import export_geojson

        # Use realistic lon/lat polygon
        wkt = "POLYGON ((-76.29 36.85, -76.28 36.85, -76.28 36.86, -76.29 36.86, -76.29 36.85))"
        detections = [_make_detection(0, wkt=wkt)]
        output_path = str(tmp_path / "crs_test.geojson")

        export_geojson(detections=detections, output_path=output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            gj = json.load(f)

        # Extract all coordinates from all features
        for feature in gj["features"]:
            geom = feature["geometry"]
            # Polygon coordinates: list of rings, each ring is list of [lon, lat] pairs
            for ring in geom.get("coordinates", []):
                for coord in ring:
                    lon, lat = coord[0], coord[1]
                    assert -180 <= lon <= 180, f"Longitude out of WGS84 range: {lon}"
                    assert -90 <= lat <= 90, f"Latitude out of WGS84 range: {lat}"

    def test_geojson_export_returns_true_on_success(self, tmp_path):
        """export_geojson() returns True on successful write."""
        from vegetation_report import export_geojson

        detections = [_make_detection(0)]
        output_path = str(tmp_path / "test.geojson")

        result = export_geojson(detections=detections, output_path=output_path)
        assert result is True


# ── Folium map ────────────────────────────────────────────────────────────────

class TestFoliumMap:
    """test_folium_map — HTML file generated, under 10MB, contains 'folium'."""

    def test_folium_map_creates_html(self, tmp_path):
        """generate_folium_map() creates an HTML file at the specified path."""
        from vegetation_report import generate_folium_map

        detections = [
            _make_detection(0, "Live Oak"),
            _make_detection(1, "Red Maple"),
        ]
        output_path = str(tmp_path / "interactive.html")

        result = generate_folium_map(
            detections=detections,
            ortho_bounds=(-76.30, 36.84, -76.28, 36.86),
            output_path=output_path,
        )

        assert result is True
        assert os.path.isfile(output_path)

    def test_folium_map_under_10mb(self, tmp_path):
        """Folium HTML file size is under 10 MB (threshold warning)."""
        from vegetation_report import generate_folium_map

        detections = [_make_detection(i, "Live Oak") for i in range(5)]
        output_path = str(tmp_path / "interactive.html")

        generate_folium_map(
            detections=detections,
            ortho_bounds=(-76.30, 36.84, -76.28, 36.86),
            output_path=output_path,
        )

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        assert size_mb < 10.0, f"Folium map is {size_mb:.1f} MB — exceeds 10 MB threshold"

    def test_folium_map_contains_folium_keyword(self, tmp_path):
        """Generated HTML contains 'folium' JavaScript library reference."""
        from vegetation_report import generate_folium_map

        detections = [_make_detection(0, "Live Oak")]
        output_path = str(tmp_path / "interactive.html")

        generate_folium_map(
            detections=detections,
            ortho_bounds=(-76.30, 36.84, -76.28, 36.86),
            output_path=output_path,
        )

        with open(output_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Folium generates HTML with L.map, leaflet references, and various js
        assert "folium" in html_content.lower() or "leaflet" in html_content.lower(), (
            "Folium-generated HTML should contain 'folium' or 'leaflet'"
        )

    def test_folium_map_no_bounds_uses_centroid_fallback(self, tmp_path):
        """generate_folium_map() handles None ortho_bounds via centroid fallback."""
        from vegetation_report import generate_folium_map

        detections = [_make_detection(0, lat=36.85, lon=-76.29)]
        output_path = str(tmp_path / "interactive_no_bounds.html")

        result = generate_folium_map(
            detections=detections,
            ortho_bounds=None,
            output_path=output_path,
        )

        assert result is True
        assert os.path.isfile(output_path)


# ── Folium skip for standard tier ─────────────────────────────────────────────

class TestFoliumSkipStandard:
    """test_folium_skip_standard — Standard tier skips Folium generation."""

    def test_standard_tier_no_folium_path(self, mocker, tmp_path):
        """With tier='standard', generate_all_outputs does not produce interactive_map_path."""
        from vegetation_report import generate_all_outputs
        import logging

        log = logging.getLogger("test")

        # Mock all sub-functions to avoid real I/O
        mocker.patch("vegetation_report.fetch_detections", return_value=[])
        mocker.patch("vegetation_report.fetch_mission_info", return_value={})
        mocker.patch("vegetation_report.generate_species_map", return_value=True)
        mocker.patch("vegetation_report.generate_health_map", return_value=True)
        mocker.patch("vegetation_report.export_geojson", return_value=True)
        mocker.patch("vegetation_report.generate_pdf", return_value=True)
        mocker.patch("vegetation_report.generate_folium_map", return_value=True)
        mocker.patch("vegetation_report.write_vegetation_summary")
        mocker.patch("vegetation_report.rasterio.open", side_effect=RuntimeError("no ortho"))

        summary = generate_all_outputs(
            mission_id="test-mission",
            ortho_path=str(tmp_path / "fake.tif"),
            output_dir=str(tmp_path / "output"),
            tier="standard",
            log=log,
        )

        assert summary.get("interactive_map_path") is None, (
            "Standard tier should not generate Folium interactive map"
        )

    def test_extended_tier_generates_folium(self, mocker, tmp_path):
        """With tier='extended', generate_all_outputs calls generate_folium_map."""
        from vegetation_report import generate_all_outputs
        import logging

        log = logging.getLogger("test")
        folium_mock = mocker.patch("vegetation_report.generate_folium_map", return_value=True)
        mocker.patch("vegetation_report.fetch_detections", return_value=[])
        mocker.patch("vegetation_report.fetch_mission_info", return_value={})
        mocker.patch("vegetation_report.generate_species_map", return_value=True)
        mocker.patch("vegetation_report.generate_health_map", return_value=True)
        mocker.patch("vegetation_report.export_geojson", return_value=True)
        mocker.patch("vegetation_report.generate_pdf", return_value=True)
        mocker.patch("vegetation_report.write_vegetation_summary")
        mocker.patch("vegetation_report.rasterio.open", side_effect=RuntimeError("no ortho"))

        generate_all_outputs(
            mission_id="test-mission",
            ortho_path=str(tmp_path / "fake.tif"),
            output_dir=str(tmp_path / "output"),
            tier="extended",
            log=log,
        )

        folium_mock.assert_called_once()


# ── PDF sections ──────────────────────────────────────────────────────────────

class TestPdfSections:
    """test_pdf_sections — PDF contains expected text sections."""

    @pytest.fixture
    def generated_pdf(self, tmp_path):
        """Create a real PDF with test detections and return its path."""
        from vegetation_report import generate_pdf

        detections = [
            _make_detection(0, "Live Oak", health_score=0.85, health_status="healthy"),
            _make_detection(1, "Red Maple", health_score=0.45, health_status="stressed"),
            _make_detection(2, "Loblolly Pine", health_score=0.72, health_status="moderate_stress"),
        ]
        output_path = str(tmp_path / "report.pdf")
        result = generate_pdf(
            detections=detections,
            output_path=output_path,
            mission_label="123 Main St — 2026-02-25",
        )
        assert result is True, "PDF generation failed in fixture"
        return output_path

    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract all text from a PDF using pypdf, normalizing whitespace."""
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages = [page.extract_text() or "" for page in reader.pages]
        # Normalize whitespace to handle line-wrapped text
        return " ".join(" ".join(page.split()) for page in pages)

    def test_pdf_has_executive_summary_section(self, generated_pdf):
        text = self._extract_pdf_text(generated_pdf)
        assert "Executive Summary" in text, (
            "PDF must contain 'Executive Summary' section"
        )

    def test_pdf_has_species_distribution_section(self, generated_pdf):
        text = self._extract_pdf_text(generated_pdf)
        assert "Species Distribution" in text, (
            "PDF must contain 'Species Distribution' section"
        )

    def test_pdf_has_methodology_section(self, generated_pdf):
        text = self._extract_pdf_text(generated_pdf)
        assert "Methodology" in text, (
            "PDF must contain 'Methodology' section"
        )

    def test_pdf_is_non_empty(self, generated_pdf):
        """PDF file is non-empty (>10KB expected for a real report)."""
        size = os.path.getsize(generated_pdf)
        assert size > 1000, f"PDF is suspiciously small: {size} bytes"


# ── PDF branding ──────────────────────────────────────────────────────────────

class TestPdfBranding:
    """test_pdf_branding — PDF contains Sentinel branding and certifications."""

    @pytest.fixture
    def generated_pdf(self, tmp_path):
        """Create a PDF and return its path."""
        from vegetation_report import generate_pdf

        detections = [_make_detection(0, "Live Oak")]
        output_path = str(tmp_path / "branded.pdf")
        generate_pdf(detections=detections, output_path=output_path, mission_label="Test Site")
        return output_path

    def _extract_pdf_text(self, pdf_path: str) -> str:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages = [page.extract_text() or "" for page in reader.pages]
        return " ".join(" ".join(page.split()) for page in pages)

    def test_pdf_contains_sentinel_aerial_inspections(self, generated_pdf):
        text = self._extract_pdf_text(generated_pdf)
        assert "Sentinel Aerial Inspections" in text, (
            "PDF must contain 'Sentinel Aerial Inspections' branding"
        )

    def test_pdf_contains_part_107(self, generated_pdf):
        text = self._extract_pdf_text(generated_pdf)
        assert "Part 107" in text, (
            "PDF must contain 'Part 107' (FAA certification)"
        )

    def test_pdf_contains_veteran_owned(self, generated_pdf):
        text = self._extract_pdf_text(generated_pdf)
        assert "Veteran-Owned" in text, (
            "PDF must contain 'Veteran-Owned' branding"
        )


# ── PDF disclaimer ────────────────────────────────────────────────────────────

class TestPdfDisclaimer:
    """test_pdf_disclaimer — PDF contains methodology disclaimer text."""

    def test_pdf_contains_methodology_disclaimer(self, tmp_path):
        """PDF must contain the full methodology disclaimer (non-negotiable)."""
        from vegetation_report import generate_pdf, METHODOLOGY_DISCLAIMER

        detections = [_make_detection(0, "Live Oak")]
        output_path = str(tmp_path / "disclaimer_test.pdf")
        generate_pdf(detections=detections, output_path=output_path)

        from pypdf import PdfReader
        reader = PdfReader(output_path)
        # Normalize whitespace: replace newlines with spaces so line-wrapped text can be found
        raw_pages = [page.extract_text() or "" for page in reader.pages]
        all_text = " ".join(
            " ".join(page.split()) for page in raw_pages
        )

        # Check for key disclaimer phrases rather than exact string (PDF text extraction may
        # introduce whitespace variations from line wrapping)
        key_phrases = [
            "AI-based classification",
            "certified arborist",
            "Sentinel Aerial Inspections",
        ]
        for phrase in key_phrases:
            assert phrase in all_text, (
                f"PDF disclaimer missing required phrase: {phrase!r}"
            )

    def test_methodology_disclaimer_constant_not_empty(self):
        """METHODOLOGY_DISCLAIMER constant is defined and non-empty."""
        from vegetation_report import METHODOLOGY_DISCLAIMER
        assert isinstance(METHODOLOGY_DISCLAIMER, str)
        assert len(METHODOLOGY_DISCLAIMER) > 100, (
            "METHODOLOGY_DISCLAIMER should be a substantial disclaimer text"
        )

    def test_pdf_footer_contains_branding_text(self):
        """PDF_FOOTER_TEXT constant contains Sentinel, Part 107, Veteran-Owned."""
        from vegetation_report import PDF_FOOTER_TEXT
        assert "Sentinel Aerial Inspections" in PDF_FOOTER_TEXT
        assert "Part 107" in PDF_FOOTER_TEXT
        assert "Veteran-Owned" in PDF_FOOTER_TEXT


# ── Supabase summary ──────────────────────────────────────────────────────────

class TestSupabaseSummary:
    """test_supabase_summary — Mocked client receives vegetation_analysis_summary with all fields."""

    def test_write_vegetation_summary_calls_upsert(self, mocker):
        """write_vegetation_summary() upserts to vegetation_analysis_summary table."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"mission_id": "test-mission"}]

        mocker.patch("supabase.create_client", return_value=mock_sb)
        mocker.patch("pipeline_utils.SUPABASE_URL", "https://test.supabase.co")
        mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "test-key")
        mocker.patch.dict(os.environ, {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_KEY": "test-key",
        })

        log = logging.getLogger("test")
        from vegetation_report import write_vegetation_summary

        summary = {
            "total_canopy_count": 5,
            "unique_species_count": 3,
            "species_distribution": {"Live Oak": 3, "Red Maple": 2},
            "avg_health_score": 0.72,
            "health_distribution": {"healthy": 3, "stressed": 2},
            "needs_attention_count": 2,
        }

        write_vegetation_summary("test-mission", summary, log)

        mock_sb.table.assert_called_with("vegetation_analysis_summary")
        mock_table.upsert.assert_called_once()

        # Verify the upsert includes mission_id and all summary fields
        call_args = mock_table.upsert.call_args[0][0]
        assert call_args["mission_id"] == "test-mission"
        assert call_args["total_canopy_count"] == 5
        assert call_args["unique_species_count"] == 3
        assert call_args["avg_health_score"] == 0.72

    def test_write_vegetation_summary_no_credentials(self, mocker):
        """write_vegetation_summary() does nothing when Supabase creds are absent."""
        mocker.patch("pipeline_utils.SUPABASE_URL", "")
        mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "")
        mocker.patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": ""})
        log = logging.getLogger("test")
        from vegetation_report import write_vegetation_summary

        # Should not raise — just warn and return
        write_vegetation_summary("test-mission", {"total_canopy_count": 0}, log)

    def test_write_vegetation_summary_handles_exception(self, mocker):
        """write_vegetation_summary() logs warning but does not raise on Supabase error."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.upsert.return_value.execute.side_effect = RuntimeError("DB error")

        mocker.patch("supabase.create_client", return_value=mock_sb)
        mocker.patch("pipeline_utils.SUPABASE_URL", "https://test.supabase.co")
        mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "test-key")
        mocker.patch.dict(os.environ, {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_SERVICE_KEY": "test-key",
        })

        log = logging.getLogger("test")
        from vegetation_report import write_vegetation_summary

        # Should not raise — exception is caught and logged as warning
        write_vegetation_summary("test-mission", {"total_canopy_count": 0}, log)

    def test_generate_all_outputs_calls_write_summary(self, mocker, tmp_path):
        """generate_all_outputs() calls write_vegetation_summary with mission_id and all fields."""
        from vegetation_report import generate_all_outputs
        import logging

        log = logging.getLogger("test")
        summary_mock = mocker.patch("vegetation_report.write_vegetation_summary")
        mocker.patch("vegetation_report.fetch_detections", return_value=[
            _make_detection(0, "Live Oak"),
        ])
        mocker.patch("vegetation_report.fetch_mission_info", return_value={})
        mocker.patch("vegetation_report.generate_species_map", return_value=True)
        mocker.patch("vegetation_report.generate_health_map", return_value=True)
        mocker.patch("vegetation_report.export_geojson", return_value=True)
        mocker.patch("vegetation_report.generate_pdf", return_value=True)
        mocker.patch("vegetation_report.rasterio.open", side_effect=RuntimeError("no ortho"))

        generate_all_outputs(
            mission_id="test-mission",
            ortho_path=str(tmp_path / "fake.tif"),
            output_dir=str(tmp_path / "out"),
            tier="standard",
            log=log,
        )

        summary_mock.assert_called_once()
        call_args = summary_mock.call_args
        assert call_args[0][0] == "test-mission"
        # Summary dict should have the key stats fields
        summary_arg = call_args[0][1]
        assert "total_canopy_count" in summary_arg
        assert "unique_species_count" in summary_arg
