# pylint: disable=[abstract-class-instantiated, arguments-differ, protected-access]
import json
import unittest
import platform
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch, MagicMock
import httpretty

from playwright.sync_api import sync_playwright
from playwright._repo_version import version as PLAYWRIGHT_VERSION
from percy.version import __version__ as SDK_VERSION
from percy.screenshot import (
    is_percy_enabled,
    fetch_percy_dom,
    percy_snapshot,
    percy_automate_screenshot,
)
import percy.screenshot as local

LABEL = local.LABEL


# mock a simple webpage to snapshot
class MockServerRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(("Snapshot Me").encode("utf-8"))

    def log_message(self, format, *args):
        return


# daemon threads automatically shut down when the main process exits
mock_server = HTTPServer(("localhost", 8000), MockServerRequestHandler)
mock_server_thread = Thread(target=mock_server.serve_forever)
mock_server_thread.daemon = True
mock_server_thread.start()

# initializing mock data
data_object = {"sync": "true", "diff": 0}


# mock helpers
def mock_healthcheck(fail=False, fail_how="error", session_type=None):
    health_body = {"success": True}
    health_headers = {"X-Percy-Core-Version": "1.0.0"}
    health_status = 200

    if fail and fail_how == "error":
        health_body = {"success": False, "error": "test"}
        health_status = 500
    elif fail and fail_how == "wrong-version":
        health_headers = {"X-Percy-Core-Version": "2.0.0"}
    elif fail and fail_how == "no-version":
        health_headers = {}

    if session_type:
        health_body["type"] = session_type

    health_body = json.dumps(health_body)
    httpretty.register_uri(
        httpretty.GET,
        "http://localhost:5338/percy/healthcheck",
        body=health_body,
        adding_headers=health_headers,
        status=health_status,
    )
    httpretty.register_uri(
        httpretty.GET,
        "http://localhost:5338/percy/dom.js",
        body="window.PercyDOM = { serialize: () => document.documentElement.outerHTML };",
        status=200,
    )


def mock_snapshot(fail=False, data=False):
    httpretty.register_uri(
        httpretty.POST,
        "http://localhost:5338/percy/snapshot",
        body=json.dumps(
            {
                "success": "false" if fail else "true",
                "error": "test" if fail else None,
                "data": data_object if data else None,
            }
        ),
        status=(500 if fail else 200),
    )


class TestPercySnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        # Launch the browser
        cls.browser = cls.p.chromium.launch(
            headless=False
        )  # Set headless=True if you don't want to see the browser
        context = cls.browser.new_context()
        cls.page = context.new_page()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        # clear the cached value for testing
        local.is_percy_enabled.cache_clear()
        local.fetch_percy_dom.cache_clear()
        self.page.goto("http://localhost:8000")
        httpretty.enable()

    def tearDown(self):
        httpretty.disable()
        httpretty.reset()

    def test_throws_error_when_a_page_is_not_provided(self):
        with self.assertRaises(Exception):
            percy_snapshot()

    def test_throws_error_when_a_name_is_not_provided(self):
        with self.assertRaises(Exception):
            percy_snapshot(self.page)

    def test_disables_snapshots_when_the_healthcheck_fails(self):
        mock_healthcheck(fail=True)

        with patch("builtins.print") as mock_print:
            percy_snapshot(self.page, "Snapshot 1")
            percy_snapshot(self.page, "Snapshot 2")

            mock_print.assert_called_with(
                f"{LABEL} Percy is not running, disabling snapshots"
            )

        self.assertEqual(httpretty.last_request().path, "/percy/healthcheck")

    def test_disables_snapshots_when_the_healthcheck_version_is_wrong(self):
        mock_healthcheck(fail=True, fail_how="wrong-version")

        with patch("builtins.print") as mock_print:
            percy_snapshot(self.page, "Snapshot 1")
            percy_snapshot(self.page, "Snapshot 2")

            mock_print.assert_called_with(
                f"{LABEL} Unsupported Percy CLI version, 2.0.0"
            )

        self.assertEqual(httpretty.last_request().path, "/percy/healthcheck")

    def test_disables_snapshots_when_the_healthcheck_version_is_missing(self):
        mock_healthcheck(fail=True, fail_how="no-version")

        with patch("builtins.print") as mock_print:
            percy_snapshot(self.page, "Snapshot 1")
            percy_snapshot(self.page, "Snapshot 2")

            mock_print.assert_called_with(
                f"{LABEL} You may be using @percy/agent which is no longer supported by this SDK. "
                "Please uninstall @percy/agent and install @percy/cli instead. "
                "https://docs.percy.io/docs/migrating-to-percy-cli"
            )

        self.assertEqual(httpretty.last_request().path, "/percy/healthcheck")

    def test_posts_snapshots_to_the_local_percy_server(self):
        mock_healthcheck()
        mock_snapshot()

        percy_snapshot(self.page, "Snapshot 1")
        response = percy_snapshot(self.page, "Snapshot 2", enable_javascript=True)

        self.assertEqual(httpretty.last_request().path, "/percy/snapshot")

        s1 = httpretty.latest_requests()[2].parsed_body
        self.assertEqual(s1["name"], "Snapshot 1")
        self.assertEqual(s1["url"], "http://localhost:8000/")
        self.assertEqual(
            s1["dom_snapshot"], "<html><head></head><body>Snapshot Me</body></html>"
        )
        self.assertRegex(s1["client_info"], r"percy-playwright-python/\d+")
        self.assertRegex(s1["environment_info"][0], r"playwright/\d+")
        self.assertRegex(s1["environment_info"][1], r"python/\d+")

        s2 = httpretty.latest_requests()[3].parsed_body
        self.assertEqual(s2["name"], "Snapshot 2")
        self.assertEqual(s2["enable_javascript"], True)
        self.assertEqual(response, None)

    def test_posts_snapshots_to_the_local_percy_server_for_sync(self):
        mock_healthcheck()
        mock_snapshot(False, True)

        percy_snapshot(self.page, "Snapshot 1")
        response = percy_snapshot(
            self.page, "Snapshot 2", enable_javascript=True, sync=True
        )

        self.assertEqual(httpretty.last_request().path, "/percy/snapshot")

        s1 = httpretty.latest_requests()[2].parsed_body
        self.assertEqual(s1["name"], "Snapshot 1")
        self.assertEqual(s1["url"], "http://localhost:8000/")
        self.assertEqual(
            s1["dom_snapshot"], "<html><head></head><body>Snapshot Me</body></html>"
        )
        self.assertRegex(s1["client_info"], r"percy-playwright-python/\d+")
        self.assertRegex(s1["environment_info"][0], r"playwright/\d+")
        self.assertRegex(s1["environment_info"][1], r"python/\d+")

        s2 = httpretty.latest_requests()[3].parsed_body
        self.assertEqual(s2["name"], "Snapshot 2")
        self.assertEqual(s2["enable_javascript"], True)
        self.assertEqual(s2["sync"], True)
        self.assertEqual(response, data_object)

        mock_healthcheck()
        mock_snapshot()

        percy_snapshot(self.page, "Snapshot")

        self.assertEqual(httpretty.last_request().path, "/percy/snapshot")

        s1 = httpretty.latest_requests()[-1].parsed_body
        self.assertEqual(s1["name"], "Snapshot")
        self.assertEqual(s1["url"], "http://localhost:8000/")
        self.assertEqual(
            s1["dom_snapshot"], "<html><head></head><body>Snapshot Me</body></html>"
        )

    def test_handles_snapshot_errors(self):
        mock_healthcheck(session_type="web")
        mock_snapshot(fail=True)

        with patch("builtins.print") as mock_print:
            percy_snapshot(self.page, "Snapshot 1")

            mock_print.assert_any_call(
                f'{LABEL} Could not take DOM snapshot "Snapshot 1"'
            )

    def test_raise_error_poa_token_with_snapshot(self):
        mock_healthcheck(session_type="automate")

        with self.assertRaises(Exception) as context:
            percy_snapshot(self.page, "Snapshot 1")

        self.assertEqual(
            "Invalid function call - "
            "percy_snapshot(). Please use percy_screenshot() "
            "function while using Percy with Automate."
            " For more information on usage of PercyScreenshot, refer https://docs.percy.io/docs"
            "/integrate-functional-testing-with-visual-testing",
            str(context.exception),
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
