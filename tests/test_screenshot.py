# pylint: disable=[abstract-class-instantiated, arguments-differ, protected-access]
import json
import unittest
import platform
from unittest.mock import patch, MagicMock
from playwright._repo_version import version as PLAYWRIGHT_VERSION
from percy.version import __version__ as SDK_VERSION
from percy.screenshot import (
    is_percy_enabled,
    fetch_percy_dom,
    percy_snapshot,
    percy_automate_screenshot,
)


class TestPercyFunctions(unittest.TestCase):
    @patch("requests.get")
    def test_is_percy_enabled(self, mock_get):
        # Mock successful health check
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"success": True, "type": "web"}
        mock_get.return_value.headers = {"x-percy-core-version": "1.0.0"}

        self.assertEqual(is_percy_enabled(), "web")

        # Clear the cache to test the unsuccessful scenario
        is_percy_enabled.cache_clear()

        # Mock unsuccessful health check
        mock_get.return_value.json.return_value = {"success": False, "error": "error"}
        self.assertFalse(is_percy_enabled())

    @patch("requests.get")
    def test_fetch_percy_dom(self, mock_get):
        # Mock successful fetch of dom.js
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = "some_js_code"

        self.assertEqual(fetch_percy_dom(), "some_js_code")

    @patch("requests.post")
    @patch("percy.screenshot.fetch_percy_dom")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_snapshot(
        self, mock_is_percy_enabled, mock_fetch_percy_dom, mock_post
    ):
        # Mock Percy enabled
        mock_is_percy_enabled.return_value = "web"
        mock_fetch_percy_dom.return_value = "some_js_code"
        page = MagicMock()
        page.evaluate.side_effect = [
            "dom_snapshot",
            json.dumps({"hashed_id": "session-id"}),
        ]
        page.url = "http://example.com"
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "success": True,
            "data": "snapshot_data",
        }

        # Call the function
        result = percy_snapshot(page, "snapshot_name")

        # Check the results
        self.assertEqual(result, "snapshot_data")
        mock_post.assert_called_once()

    @patch("requests.post")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_automate_screenshot(self, mock_is_percy_enabled, mock_post):
        # Mock Percy enabled for automate
        is_percy_enabled.cache_clear()
        mock_is_percy_enabled.return_value = "automate"
        page = MagicMock()

        page._impl_obj._guid = "page@abc"
        page.main_frame._impl_obj._guid = "frame@abc"
        page.context.browser._impl_obj._guid = "browser@abc"
        page.evaluate.return_value = '{"hashed_id": "session_id"}'

        # Mock the response for the POST request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "success": True,
            "data": "screenshot_data",
        }

        # Call the function
        result = percy_automate_screenshot(page, "screenshot_name")

        # Assertions
        self.assertEqual(result, "screenshot_data")
        mock_post.assert_called_once_with(
            "http://localhost:5338/percy/automateScreenshot",
            json={
                "client_info": f"percy-playwright-python/{SDK_VERSION}",
                "environment_info": [
                    f"playwright/{PLAYWRIGHT_VERSION}",
                    f"python/{platform.python_version()}",
                ],
                "sessionId": "session_id",
                "pageGuid": "page@abc",
                "frameGuid": "frame@abc",
                "framework": "playwright",
                "snapshotName": "screenshot_name",
                "options": {},
            },
            timeout=600,
        )

    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_automate_screenshot_invalid_call(self, mock_is_percy_enabled):
        # Mock Percy enabled for web
        mock_is_percy_enabled.return_value = "web"
        page = MagicMock()

        # Call the function and expect an exception
        with self.assertRaises(Exception) as context:
            percy_automate_screenshot(page, "screenshot_name")

        self.assertTrue("Invalid function call" in str(context.exception))


if __name__ == "__main__":
    unittest.main()
