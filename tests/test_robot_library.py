"""Tests for Robot Framework library integration.

These tests mock playwright at module level so they can run without
playwright installed, since percy.screenshot imports it at top level.
"""
import sys
from unittest.mock import MagicMock, patch

# Mock playwright before any percy imports  pylint: disable=protected-access
_mock_playwright = MagicMock()
_mock_playwright._repo_version.version = "1.50.0"  # pylint: disable=protected-access
_mock_playwright.sync_api.Error = Exception
_mock_playwright.sync_api.TimeoutError = TimeoutError
sys.modules.setdefault("playwright", _mock_playwright)
sys.modules.setdefault(  # pylint: disable=protected-access
    "playwright._repo_version", _mock_playwright._repo_version
)
sys.modules.setdefault("playwright.sync_api", _mock_playwright.sync_api)

from percy.robot_library import (  # noqa: E402 pylint: disable=wrong-import-position
    PercyLibrary,
    _parse_bool,
    _parse_csv,
    _parse_json,
    _parse_widths,
)


class TestParseHelpers:
    def test_parse_bool_none(self):
        assert _parse_bool(None) is None

    def test_parse_bool_true(self):
        assert _parse_bool("True") is True
        assert _parse_bool("true") is True
        assert _parse_bool("1") is True

    def test_parse_bool_false(self):
        assert _parse_bool("False") is False
        assert _parse_bool("no") is False

    def test_parse_widths_string(self):
        assert _parse_widths("375,768,1280") == [375, 768, 1280]

    def test_parse_widths_none(self):
        assert _parse_widths(None) is None

    def test_parse_csv_string(self):
        assert _parse_csv("regression, homepage") == ["regression", "homepage"]

    def test_parse_json_string(self):
        assert _parse_json('{"key": true}') == {"key": True}

    def test_parse_json_none(self):
        assert _parse_json(None) is None


class TestPercyLibraryKeywords:
    def test_import_succeeds(self):
        assert PercyLibrary is not None

    @patch("percy.robot_library._get_screenshot_module")
    @patch("percy.robot_library.BuiltIn")
    def test_percy_snapshot_keyword(self, mock_builtin, mock_get_mod):
        mock_mod = MagicMock()
        mock_get_mod.return_value = mock_mod
        mock_builtin.return_value.get_library_instance.return_value = MagicMock()

        lib = PercyLibrary()
        lib.percy_snapshot_keyword("Homepage", widths="375,1280", labels="regression,v2")

        mock_mod.percy_snapshot.assert_called_once()
        call_kwargs = mock_mod.percy_snapshot.call_args[1]
        assert call_kwargs["widths"] == [375, 1280]
        assert call_kwargs["labels"] == ["regression", "v2"]

    @patch("percy.robot_library._get_screenshot_module")
    def test_percy_is_running(self, mock_get_mod):
        mock_mod = MagicMock()
        mock_get_mod.return_value = mock_mod

        mock_mod._is_percy_enabled.return_value = {"session_type": "web"}  # pylint: disable=protected-access
        lib = PercyLibrary()
        assert lib.percy_is_running_keyword() is True

        mock_mod._is_percy_enabled.return_value = False  # pylint: disable=protected-access
        assert lib.percy_is_running_keyword() is False

    @patch("percy.robot_library._get_screenshot_module")
    def test_create_region(self, mock_get_mod):
        mock_mod = MagicMock()
        mock_mod.create_region.return_value = {
            "algorithm": "ignore",
            "elementSelector": {"elementCSS": ".ad"},
        }
        mock_get_mod.return_value = mock_mod

        lib = PercyLibrary()
        result = lib.create_percy_region_keyword(algorithm="ignore", element_css=".ad")
        assert result["algorithm"] == "ignore"
        mock_mod.create_region.assert_called_once()
