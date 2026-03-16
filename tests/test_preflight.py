"""Tests for pipeline_utils.preflight_check()."""

import logging
from unittest.mock import patch, MagicMock

import pytest

from pipeline_utils import preflight_check


class TestPreflightAllDown:
    """When all services are unreachable, preflight reports them as missing."""

    def test_returns_all_false_when_nothing_running(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("pipeline_utils.shutil.which", return_value=None), \
             patch("requests.get", side_effect=ConnectionError("refused")):
            status = preflight_check(require_n8n=False, require_ffmpeg=False, require_nodeodm=False)

        assert status["n8n"] is False
        assert status["ffmpeg"] is False
        assert status["nodeodm"] is False


class TestPreflightAllUp:
    """When all services respond 200, preflight reports them as OK."""

    def test_returns_all_true_when_services_healthy(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("pipeline_utils.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch("requests.get", return_value=mock_resp), \
             patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "key"}), \
             patch("pipeline_utils.SUPABASE_URL", "https://x.supabase.co"), \
             patch("pipeline_utils.SUPABASE_SERVICE_KEY", "key"):
            status = preflight_check()

        assert status["n8n"] is True
        assert status["ffmpeg"] is True
        assert status["nodeodm"] is True
        assert status["supabase"] is True


class TestPreflightPartial:
    """Mixed service state — some up, some down."""

    def test_n8n_up_ffmpeg_missing(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        def mock_get(url, **kwargs):
            if "5678" in url:
                return mock_resp
            raise ConnectionError("refused")

        with patch("pipeline_utils.shutil.which", return_value=None), \
             patch("requests.get", side_effect=mock_get):
            status = preflight_check(require_n8n=False)

        assert status["n8n"] is True
        assert status["ffmpeg"] is False
        assert status["nodeodm"] is False


class TestPreflightLogging:
    """Preflight logs errors for required services and warnings for optional."""

    def test_required_n8n_logs_error(self, caplog):
        with patch("pipeline_utils.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch("requests.get", side_effect=ConnectionError("refused")), \
             caplog.at_level(logging.ERROR):
            preflight_check(require_n8n=True)

        assert any("n8n is not running" in r.message for r in caplog.records)

    def test_optional_n8n_logs_warning(self, caplog):
        with patch("pipeline_utils.shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch("requests.get", side_effect=ConnectionError("refused")), \
             caplog.at_level(logging.WARNING):
            preflight_check(require_n8n=False)

        assert any("n8n is not running" in r.message for r in caplog.records)


class TestPreflightReturnType:
    """Preflight always returns a dict with expected keys."""

    def test_returns_dict_with_all_keys(self):
        with patch("pipeline_utils.shutil.which", return_value=None), \
             patch("requests.get", side_effect=ConnectionError):
            status = preflight_check()

        assert isinstance(status, dict)
        assert "n8n" in status
        assert "ffmpeg" in status
        assert "nodeodm" in status
        assert "supabase" in status
