# pylint: disable=[abstract-class-instantiated, arguments-differ, protected-access, too-many-lines]
import json
import unittest
import platform
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch, MagicMock, call
import httpretty

from playwright.sync_api import sync_playwright
from playwright._repo_version import version as PLAYWRIGHT_VERSION
from percy.version import __version__ as SDK_VERSION
from percy.screenshot import (
    is_percy_enabled,
    fetch_percy_dom,
    percy_snapshot,
    percy_automate_screenshot,
    create_region,
    is_responsive_snapshot_capture,
    calculate_default_height,
    get_widths_for_multi_dom,
    capture_responsive_dom,
    change_window_dimension_and_wait,
    log
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
# pylint: disable=too-many-arguments
def mock_healthcheck(
    fail=False, fail_how="error", session_type=None,
    widths=None, config=None, device_details=None
):
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
    if widths:
        health_body["widths"] = widths
    if config:
        health_body["config"] = config
    if device_details:
        health_body["deviceDetails"] = device_details

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
        body=(
            "window.PercyDOM = { serialize: () => { return { html: "
            "document.documentElement.outerHTML } }, waitForResize: () => { "
            "if(!window.resizeCount) { window.addEventListener('resize', () => "
            "window.resizeCount++) } window.resizeCount = 0; }}"
        ),
        status=200,
    )


def mock_logger():
    httpretty.register_uri(
        httpretty.POST,
        "http://localhost:5338/percy/log",
        body=json.dumps({"success": True}),
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
            headless=True
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
                "https://www.browserstack.com/docs/percy/migration/migrate-to-cli"
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
            s1["dom_snapshot"]["html"], "<html><head></head><body>Snapshot Me</body></html>"
        )
        self.assertIn("cookies", s1["dom_snapshot"])
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
            s1["dom_snapshot"]["html"], "<html><head></head><body>Snapshot Me</body></html>"
        )
        self.assertIn("cookies", s1["dom_snapshot"])
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
            s1["dom_snapshot"]["html"], "<html><head></head><body>Snapshot Me</body></html>"
        )
        self.assertIn("cookies", s1["dom_snapshot"])

    def test_handles_snapshot_errors(self):
        mock_healthcheck(session_type="web")
        mock_snapshot(fail=True)
        mock_logger()

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
            " For more information on usage of PercyScreenshot, refer https://www.browserstack.com/"
            "docs/percy/integrate/functional-and-visual",
            str(context.exception),
        )


class TestPercyFunctions(unittest.TestCase):
    @patch("requests.get")
    def test_is_percy_enabled(self, mock_get):
        # Mock successful health check
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "success": True,
            "type": "web",
            "config": {},
            "widths": {},
            "deviceDetails": [],
        }
        mock_get.return_value.headers = {"x-percy-core-version": "1.0.0"}

        self.assertEqual(
            is_percy_enabled(),
            {
                "session_type": "web",
                "config": {},
                "widths": {},
                "device_details": [],
            },
        )

        # Clear the cache to test the unsuccessful scenario
        is_percy_enabled.cache_clear()

        # Mock unsuccessful health check
        mock_get.return_value.json.return_value = {"success": False, "error": "error"}
        self.assertFalse(is_percy_enabled())

    @patch("requests.get")
    def test_fetch_percy_dom(self, mock_get):
        # Mock successful fetch of dom.js
        fetch_percy_dom.cache_clear()
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = "some_js_code"

        self.assertEqual(fetch_percy_dom(), "some_js_code")

    @patch("requests.get")
    def test_fetch_percy_dom_raises(self, mock_get):
        fetch_percy_dom.cache_clear()
        mock_get.return_value.raise_for_status.side_effect = Exception("boom")

        with self.assertRaises(Exception):
            fetch_percy_dom()

    @patch("requests.post")
    @patch("percy.screenshot.fetch_percy_dom")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_snapshot(
        self, mock_is_percy_enabled, mock_fetch_percy_dom, mock_post
    ):
        # Mock Percy enabled
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {},
            "widths": {},
            "device_details": [],
        }
        mock_fetch_percy_dom.return_value = "some_js_code"
        page = MagicMock()
        page.evaluate.side_effect = [None, {"html": "<html></html>"}]
        page.context.cookies.return_value = []
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
    @patch("percy.screenshot.fetch_percy_dom")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_snapshot_includes_cookies(
        self, mock_is_percy_enabled, mock_fetch_percy_dom, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {},
            "widths": {},
            "device_details": [],
        }
        mock_fetch_percy_dom.return_value = "some_js_code"
        page = MagicMock()
        page.evaluate.side_effect = [None, {"html": "<html></html>"}]
        page.context.cookies.return_value = [{"name": "foo", "value": "bar"}]
        page.url = "http://example.com"
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "success": True,
            "data": "snapshot_data",
        }

        percy_snapshot(page, "snapshot_name")

        posted = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            posted["dom_snapshot"]["cookies"], [{"name": "foo", "value": "bar"}]
        )

    @patch("requests.post")
    @patch("percy.screenshot.capture_responsive_dom")
    @patch("percy.screenshot.fetch_percy_dom")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_snapshot_responsive_capture(
        self,
        mock_is_percy_enabled,
        mock_fetch_percy_dom,
        mock_capture_responsive_dom,
        mock_post,
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {"snapshot": {"responsiveSnapshotCapture": True}},
            "widths": {"config": [375, 1280]},
            "device_details": [{"width": 375, "height": 667}],
        }
        mock_fetch_percy_dom.return_value = "some_js_code"
        mock_capture_responsive_dom.return_value = [
            {"html": "<html></html>", "width": 375},
            {"html": "<html></html>", "width": 1280},
        ]
        page = MagicMock()
        page.evaluate.return_value = None
        page.context.cookies.return_value = [{"name": "foo", "value": "bar"}]
        page.url = "http://example.com"
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "success": True,
            "data": "snapshot_data",
        }

        percy_snapshot(page, "snapshot_name")

        mock_capture_responsive_dom.assert_called_once_with(
            page,
            {"config": [375, 1280]},
            [{"width": 375, "height": 667}],
            [{"name": "foo", "value": "bar"}],
        )
        posted = mock_post.call_args.kwargs["json"]
        self.assertEqual(posted["dom_snapshot"], mock_capture_responsive_dom.return_value)

    @patch("requests.post")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_automate_screenshot(self, mock_is_percy_enabled, mock_post):
        # Mock Percy enabled for automate
        is_percy_enabled.cache_clear()
        mock_is_percy_enabled.return_value = {
            "session_type": "automate",
            "config": {},
            "widths": {},
            "device_details": [],
        }
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
    def test_percy_automate_screenshot_percy_disabled(self, mock_is_percy_enabled):
        """Test percy_automate_screenshot when Percy is not enabled."""
        is_percy_enabled.cache_clear()
        mock_is_percy_enabled.return_value = False

        page = MagicMock()
        result = percy_automate_screenshot(page, "screenshot_name")

        # Should return None when Percy is disabled
        self.assertIsNone(result)

    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_automate_screenshot_invalid_call(self, mock_is_percy_enabled):
        # Mock Percy enabled for web
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {},
            "widths": {},
            "device_details": [],
        }
        page = MagicMock()

        # Call the function and expect an exception
        with self.assertRaises(Exception) as context:
            percy_automate_screenshot(page, "screenshot_name")

        self.assertTrue("Invalid function call" in str(context.exception))

    @patch("requests.post")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_automate_screenshot_with_options(self, mock_is_percy_enabled, mock_post):
        """Test percy_automate_screenshot when options are provided (not None)."""
        # Mock Percy enabled for automate
        is_percy_enabled.cache_clear()
        mock_is_percy_enabled.return_value = {
            "session_type": "automate",
            "config": {},
            "widths": {},
            "device_details": [],
        }
        page = MagicMock()

        page._impl_obj._guid = "page@xyz"
        page.main_frame._impl_obj._guid = "frame@xyz"
        page.context.browser._impl_obj._guid = "browser@xyz"
        page.evaluate.return_value = '{"hashed_id": "session_xyz"}'

        # Mock the response for the POST request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "success": True,
            "data": "screenshot_with_options",
        }

        # Call the function with explicit options (not None)
        test_options = {"freeze_animated_image": True, "freeze_image_by_selectors": [".animated"]}
        result = percy_automate_screenshot(page, "screenshot_name", options=test_options)

        # Assertions
        self.assertEqual(result, "screenshot_with_options")
        call_args = mock_post.call_args
        self.assertEqual(call_args.kwargs["json"]["options"], test_options)


class TestScreenshotEdgeCases(unittest.TestCase):
    def setUp(self):
        is_percy_enabled.cache_clear()
        fetch_percy_dom.cache_clear()

    @patch("requests.get")
    def test_is_percy_enabled_request_error(self, mock_get):
        mock_get.side_effect = Exception("boom")
        with patch.object(local, "PERCY_DEBUG", True), patch("builtins.print") as mock_print:
            self.assertFalse(is_percy_enabled())
            mock_print.assert_any_call(
                f"{LABEL} Percy is not running, disabling snapshots"
            )

    @patch("requests.get")
    def test_is_percy_enabled_raise_for_status(self, mock_get):
        mock_get.return_value.raise_for_status.side_effect = Exception("boom")
        mock_get.return_value.json.return_value = {"success": True}
        with patch.object(local, "PERCY_DEBUG", False):
            self.assertFalse(is_percy_enabled())

    def test_log_debug_when_enabled(self):
        with patch("requests.post", side_effect=Exception("boom")), patch.object(
            local, "PERCY_DEBUG", True
        ), patch("builtins.print") as mock_print:
            log("message", lvl="debug")
            mock_print.assert_any_call("Sending log to CLI Failed boom")
            mock_print.assert_any_call(f"{LABEL} message")

    def test_log_debug_when_disabled(self):
        with patch("requests.post") as mock_post, patch.object(
            local, "PERCY_DEBUG", False
        ), patch("builtins.print") as mock_print:
            mock_post.return_value.status_code = 200
            log("message", lvl="debug")
            mock_print.assert_not_called()

    def test_log_info_level(self):
        """Test log function with info level (should always print)."""
        with patch("requests.post") as mock_post, patch.object(
            local, "PERCY_DEBUG", False
        ), patch("builtins.print") as mock_print:
            mock_post.return_value.status_code = 200
            log("info message", lvl="info")
            mock_print.assert_called_once_with(f"{LABEL} info message")

    def test_log_exception_debug_disabled(self):
        """Test log function when exception occurs and PERCY_DEBUG is False."""
        with patch("requests.post", side_effect=Exception("connection error")), patch.object(
            local, "PERCY_DEBUG", False
        ), patch("builtins.print") as mock_print:
            log("message with error", lvl="info")
            # Should still print the message in finally block, but not the exception
            mock_print.assert_called_once_with(f"{LABEL} message with error")

    def test_change_window_dimension_and_wait_errors(self):
        page = MagicMock()
        page.set_viewport_size.side_effect = Exception("boom")
        page.wait_for_function.side_effect = Exception("boom")

        with patch("percy.screenshot.log") as mock_log:
            change_window_dimension_and_wait(page, 100, 200, 1)

        self.assertEqual(mock_log.call_count, 2)

    def test_capture_responsive_dom_no_reload_or_sleep(self):
        page = MagicMock()
        page.viewport_size = {"width": 800, "height": 600}
        page.evaluate = MagicMock()
        page.reload = MagicMock()

        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE", None), patch.object(
            local, "RESPONSIVE_CAPTURE_SLEEP_TIME", None
        ), patch(
            "percy.screenshot.get_widths_for_multi_dom"
        ) as mock_widths, patch(
            "percy.screenshot.get_serialized_dom"
        ) as mock_serialized, patch(
            "percy.screenshot.change_window_dimension_and_wait"
        ) as mock_resize:
            mock_widths.return_value = [{"width": 800, "height": 600}]
            mock_serialized.return_value = {"html": "<html></html>"}

            capture_responsive_dom(
                page, {"config": [800]}, [], [{"name": "foo", "value": "bar"}]
            )

        page.reload.assert_not_called()
        page.evaluate.assert_any_call("PercyDOM.waitForResize()")
        mock_resize.assert_called_once_with(page, 800, 600, 1)

    def test_capture_responsive_dom_none_viewport_falls_back_to_js(self):
        page = MagicMock()
        page.viewport_size = None
        page.evaluate = MagicMock(
            side_effect=lambda expr: {"width": 1024, "height": 768}
            if "innerWidth" in expr
            else None
        )
        page.reload = MagicMock()

        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE", None), patch.object(
            local, "RESPONSIVE_CAPTURE_SLEEP_TIME", None
        ), patch(
            "percy.screenshot.get_widths_for_multi_dom"
        ) as mock_widths, patch(
            "percy.screenshot.get_serialized_dom"
        ) as mock_serialized, patch(
            "percy.screenshot.change_window_dimension_and_wait"
        ) as mock_resize:
            mock_widths.return_value = [{"width": 1024, "height": 768}]
            mock_serialized.return_value = {"html": "<html></html>"}

            capture_responsive_dom(
                page, {"config": [1024]}, [], [{"name": "foo", "value": "bar"}]
            )

        page.evaluate.assert_any_call(
            "() => ({ width: window.innerWidth, height: window.innerHeight })"
        )
        mock_resize.assert_called_once_with(page, 1024, 768, 1)

    @patch("requests.post")
    @patch("percy.screenshot.fetch_percy_dom")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_snapshot_response_error(
        self, mock_is_percy_enabled, mock_fetch_percy_dom, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {},
            "widths": {},
            "device_details": [],
        }
        mock_fetch_percy_dom.return_value = "some_js_code"
        page = MagicMock()
        page.evaluate.side_effect = [None, {"html": "<html></html>"}]
        page.context.cookies.return_value = []
        page.url = "http://example.com"
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "success": False,
            "error": "bad",
        }

        with patch("percy.screenshot.log") as mock_log:
            result = percy_snapshot(page, "snapshot_name")

        self.assertIsNone(result)
        mock_log.assert_any_call('Could not take DOM snapshot "snapshot_name"')

    @patch("requests.post")
    @patch("percy.screenshot.fetch_percy_dom")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_snapshot_request_error(
        self, mock_is_percy_enabled, mock_fetch_percy_dom, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {},
            "widths": {},
            "device_details": [],
        }
        mock_fetch_percy_dom.return_value = "some_js_code"
        page = MagicMock()
        page.evaluate.side_effect = [None, {"html": "<html></html>"}]
        page.context.cookies.return_value = []
        page.url = "http://example.com"
        mock_post.side_effect = Exception("boom")

        with patch("percy.screenshot.log") as mock_log:
            result = percy_snapshot(page, "snapshot_name")

        self.assertIsNone(result)
        mock_log.assert_any_call('Could not take DOM snapshot "snapshot_name"')

    @patch("requests.post")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_automate_screenshot_response_error(
        self, mock_is_percy_enabled, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "automate",
            "config": {},
            "widths": {},
            "device_details": [],
        }
        page = MagicMock()
        page._impl_obj._guid = "page@abc"
        page.main_frame._impl_obj._guid = "frame@abc"
        page.context.browser._impl_obj._guid = "browser@abc"
        page.evaluate.return_value = '{"hashed_id": "session_id"}'
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "success": False,
            "error": "bad",
        }

        with patch("percy.screenshot.log") as mock_log:
            result = percy_automate_screenshot(page, "screenshot_name")

        self.assertIsNone(result)
        mock_log.assert_any_call('Could not take Screenshot "screenshot_name"')

    @patch("requests.post")
    @patch("percy.screenshot.is_percy_enabled")
    def test_percy_automate_screenshot_request_error(
        self, mock_is_percy_enabled, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "automate",
            "config": {},
            "widths": {},
            "device_details": [],
        }
        page = MagicMock()
        page._impl_obj._guid = "page@abc"
        page.main_frame._impl_obj._guid = "frame@abc"
        page.context.browser._impl_obj._guid = "browser@abc"
        page.evaluate.return_value = '{"hashed_id": "session_id"}'
        mock_post.side_effect = Exception("boom")

        with patch("percy.screenshot.log") as mock_log:
            result = percy_automate_screenshot(page, "screenshot_name")

        self.assertIsNone(result)
        mock_log.assert_any_call('Could not take Screenshot "screenshot_name"')

class TestCreateRegion(unittest.TestCase):

    def test_create_region_with_all_params(self):
        result = create_region(
            boundingBox={"x": 10, "y": 20, "width": 100, "height": 200},
            elementXpath="//*[@id='test']",
            elementCSS=".test-class",
            padding=10,
            algorithm="intelliignore",
            diffSensitivity=0.8,
            imageIgnoreThreshold=0.5,
            carouselsEnabled=True,
            bannersEnabled=False,
            adsEnabled=True,
            diffIgnoreThreshold=0.2
        )

        expected_result = {
            "algorithm": "intelliignore",
            "elementSelector": {
                "boundingBox": {"x": 10, "y": 20, "width": 100, "height": 200},
                "elementXpath": "//*[@id='test']",
                "elementCSS": ".test-class"
            },
            "padding": 10,
            "configuration": {
                "diffSensitivity": 0.8,
                "imageIgnoreThreshold": 0.5,
                "carouselsEnabled": True,
                "bannersEnabled": False,
                "adsEnabled": True
            },
            "assertion": {
                "diffIgnoreThreshold": 0.2
            }
        }

        self.assertEqual(result, expected_result)


class TestResponsiveHelpers(unittest.TestCase):
    def test_is_responsive_snapshot_capture_from_kwargs(self):
        self.assertTrue(is_responsive_snapshot_capture({}, responsive_snapshot_capture=True))
        self.assertTrue(is_responsive_snapshot_capture({}, responsiveSnapshotCapture=True))

    def test_is_responsive_snapshot_capture_from_config(self):
        config = {"snapshot": {"responsiveSnapshotCapture": True}}
        self.assertTrue(is_responsive_snapshot_capture(config))

    def test_is_responsive_snapshot_capture_defer_uploads(self):
        config = {
            "percy": {"deferUploads": True},
            "snapshot": {"responsiveSnapshotCapture": True},
        }
        self.assertFalse(is_responsive_snapshot_capture(config, responsiveSnapshotCapture=True))

    def test_calculate_default_height_env_disabled(self):
        page = MagicMock()
        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT", None):
            self.assertEqual(calculate_default_height(page, 123), 123)
            page.evaluate.assert_not_called()

    def test_calculate_default_height_env_enabled(self):
        page = MagicMock()
        page.evaluate.return_value = 456
        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT", "1"):
            self.assertEqual(calculate_default_height(page, 123, min_height=200), 456)
            page.evaluate.assert_called_once_with(
                "(minH) => window.outerHeight - window.innerHeight + minH", 200
            )

    def test_calculate_default_height_env_enabled_handles_error(self):
        page = MagicMock()
        page.evaluate.side_effect = Exception("boom")
        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT", "1"):
            self.assertEqual(calculate_default_height(page, 321), 321)

    def test_get_widths_for_multi_dom(self):
        eligible_widths = {"mobile": [375], "config": [1280]}
        device_details = [{"width": 375, "height": 667}]
        widths = get_widths_for_multi_dom(eligible_widths, device_details, 900)

        self.assertEqual(
            widths,
            [
                {"width": 375, "height": 667},
                {"width": 1280, "height": 900},
            ],
        )

    def test_get_widths_for_multi_dom_user_width_override(self):
        eligible_widths = {"mobile": [375], "config": [1280]}
        device_details = []
        widths = get_widths_for_multi_dom(
            eligible_widths, device_details, 900, width=1024
        )

        self.assertEqual(
            widths,
            [
                {"width": 375, "height": 900},
                {"width": 1024, "height": 900},
            ],
        )

    def test_get_widths_for_multi_dom_with_widths_list(self):
        """Test get_widths_for_multi_dom with user-provided widths list."""
        eligible_widths = {"mobile": [375], "config": [1280]}
        device_details = [{"width": 375, "height": 667}]
        # Pass widths as a list (not using width parameter)
        widths = get_widths_for_multi_dom(
            eligible_widths, device_details, 900, widths=[800, 1024]
        )

        # Should include mobile width with device height, and user widths
        self.assertEqual(len(widths), 3)
        self.assertIn({"width": 375, "height": 667}, widths)
        self.assertIn({"width": 800, "height": 900}, widths)
        self.assertIn({"width": 1024, "height": 900}, widths)

    def test_get_widths_for_multi_dom_mobile_without_device_info(self):
        """Test get_widths_for_multi_dom when device_info is None for mobile width."""
        eligible_widths = {"mobile": [375, 768], "config": [1280]}
        # Only provide device details for 375, not for 768
        device_details = [{"width": 375, "height": 667}]
        widths = get_widths_for_multi_dom(eligible_widths, device_details, 900)

        # 768 should use default_height since no device_info
        expected = [
            {"width": 375, "height": 667},
            {"width": 768, "height": 900},  # Uses default_height
            {"width": 1280, "height": 900},
        ]
        self.assertEqual(widths, expected)

    def test_get_widths_for_multi_dom_duplicate_widths(self):
        """Test get_widths_for_multi_dom when same width appears in mobile and config."""
        eligible_widths = {"mobile": [375, 1280], "config": [1280, 1920]}
        device_details = [{"width": 375, "height": 667}, {"width": 1280, "height": 800}]
        widths = get_widths_for_multi_dom(eligible_widths, device_details, 900)

        # 1280 should only appear once (from mobile with device height)
        self.assertEqual(len(widths), 3)
        self.assertIn({"width": 375, "height": 667}, widths)
        self.assertIn({"width": 1280, "height": 800}, widths)  # From mobile with device info
        self.assertIn({"width": 1920, "height": 900}, widths)

    def test_get_widths_for_multi_dom_no_mobile_widths(self):
        """Test get_widths_for_multi_dom with no mobile widths."""
        eligible_widths = {"mobile": [], "config": [1280, 1920]}
        device_details = []
        widths = get_widths_for_multi_dom(eligible_widths, device_details, 900)

        # Should only have config widths
        self.assertEqual(len(widths), 2)
        self.assertIn({"width": 1280, "height": 900}, widths)
        self.assertIn({"width": 1920, "height": 900}, widths)

    def test_get_widths_for_multi_dom_mobile_width_already_in_map(self):
        """Test when a mobile width appears multiple times (edge case for branch coverage)."""
        # This is a contrived test to hit the branch where width is already in width_height_map
        # during the mobile widths loop
        eligible_widths = {"mobile": [375, 375], "config": [1280]}  # Duplicate 375
        device_details = [{"width": 375, "height": 667}]
        widths = get_widths_for_multi_dom(eligible_widths, device_details, 900)

        # Should only have 375 once and 1280
        self.assertEqual(len(widths), 2)
        self.assertIn({"width": 375, "height": 667}, widths)
        self.assertIn({"width": 1280, "height": 900}, widths)

    def test_capture_responsive_dom_calls_resize_reload_sleep(self):
        page = MagicMock()
        page.viewport_size = {"width": 800, "height": 600}
        page.evaluate = MagicMock()
        page.reload = MagicMock()

        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE", "1"), patch.object(
            local, "RESPONSIVE_CAPTURE_SLEEP_TIME", "1"
        ), patch(
            "percy.screenshot.get_widths_for_multi_dom"
        ) as mock_widths, patch(
            "percy.screenshot.get_serialized_dom"
        ) as mock_serialized, patch(
            "percy.screenshot.change_window_dimension_and_wait"
        ) as mock_resize, patch(
            "percy.screenshot.fetch_percy_dom"
        ) as mock_fetch, patch(
            "percy.screenshot.sleep"
        ) as mock_sleep:
            mock_widths.return_value = [
                {"width": 800, "height": 600},
                {"width": 1200, "height": 700},
            ]
            mock_serialized.side_effect = [
                {"html": "<html></html>"},
                {"html": "<html></html>"},
            ]
            mock_fetch.return_value = "dom-script"

            result = capture_responsive_dom(
                page, {"config": [800, 1200]}, [], [{"name": "foo", "value": "bar"}]
            )

        page.evaluate.assert_any_call("PercyDOM.waitForResize()")
        page.evaluate.assert_any_call("dom-script")
        self.assertEqual(page.evaluate.call_count, 3)
        self.assertEqual(page.reload.call_count, 2)
        mock_sleep.assert_any_call(1)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_resize.assert_has_calls(
            [
                call(page, 1200, 700, 1),
                call(page, 800, 600, 2),
            ]
        )
        self.assertEqual(result[0]["width"], 800)
        self.assertEqual(result[1]["width"], 1200)

    def test_create_region_with_minimal_params(self):
        result = create_region(
            algorithm="standard",
            boundingBox={"x": 10, "y": 20, "width": 100, "height": 200}
        )

        expected_result = {
            "algorithm": "standard",
            "elementSelector": {
                "boundingBox": {"x": 10, "y": 20, "width": 100, "height": 200}
            }
        }

        self.assertEqual(result, expected_result)

    def test_create_region_with_padding(self):
        result = create_region(
            algorithm="ignore",
            padding=15
        )

        expected_result = {
            "algorithm": "ignore",
            "elementSelector": {},
            "padding": 15
        }

        self.assertEqual(result, expected_result)

    def test_create_region_with_configuration_only_for_valid_algorithms(self):
        result = create_region(
            algorithm="intelliignore",
            diffSensitivity=0.9,
            imageIgnoreThreshold=0.7
        )

        expected_result = {
            "algorithm": "intelliignore",
            "elementSelector": {},
            "configuration": {
                "diffSensitivity": 0.9,
                "imageIgnoreThreshold": 0.7
            }
        }

        self.assertEqual(result, expected_result)

    def test_create_region_with_diffIgnoreThreshold_in_assertion(self):
        result = create_region(
            algorithm="standard",
            diffIgnoreThreshold=0.3
        )

        expected_result = {
            "algorithm": "standard",
            "elementSelector": {},
            "assertion": {
                "diffIgnoreThreshold": 0.3
            }
        }

        self.assertEqual(result, expected_result)

    def test_create_region_with_invalid_algorithm(self):
        result = create_region(
            algorithm="invalid_algorithm"
        )

        expected_result = {
            "algorithm": "invalid_algorithm",
            "elementSelector": {}
        }

        self.assertEqual(result, expected_result)


if __name__ == "__main__":
    unittest.main()
