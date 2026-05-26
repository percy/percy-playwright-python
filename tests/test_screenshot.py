# pylint: disable=[abstract-class-instantiated, arguments-differ, protected-access, too-many-lines]
import json
import unittest
import platform
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch, MagicMock, call
import httpretty

from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from playwright._repo_version import version as PLAYWRIGHT_VERSION
from percy.version import __version__ as SDK_VERSION
from percy.screenshot import (
    _is_percy_enabled,
    fetch_percy_dom,
    percy_snapshot,
    percy_automate_screenshot,
    create_region,
    is_responsive_snapshot_capture,
    calculate_default_height,
    get_responsive_widths,
    capture_responsive_dom,
    change_window_dimension_and_wait,
    get_serialized_dom,
    process_frame,
    log,
    _resolve_readiness_config,
    _wait_for_ready,
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
        local._is_percy_enabled.cache_clear()
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


class TestReadinessGate(unittest.TestCase):
    """Unit tests for _wait_for_ready / _resolve_readiness_config using a
    fully-mocked Page. Bypasses real Playwright CDP traffic, so cannot hang
    on real in-page observers like the integration-style tests did."""

    def test_resolve_readiness_config_shallow_merges(self):
        merged = _resolve_readiness_config(
            {'snapshot': {'readiness': {'preset': 'balanced', 'timeoutMs': 8000}}},
            {'readiness': {'stabilityWindowMs': 500}}
        )
        self.assertEqual(merged, {
            'preset': 'balanced', 'timeoutMs': 8000, 'stabilityWindowMs': 500
        })

    def test_resolve_readiness_config_per_snapshot_wins(self):
        merged = _resolve_readiness_config(
            {'snapshot': {'readiness': {'preset': 'balanced'}}},
            {'readiness': {'preset': 'strict'}}
        )
        self.assertEqual(merged['preset'], 'strict')

    def test_resolve_readiness_config_handles_none_snapshot(self):
        # Defensive: CLI healthcheck could return snapshot: null
        merged = _resolve_readiness_config({'snapshot': None}, {})
        self.assertEqual(merged, {})

    def test_resolve_readiness_config_handles_non_dict_inputs(self):
        merged = _resolve_readiness_config(
            {'snapshot': {'readiness': 'not-a-dict'}},
            {'readiness': 12345}
        )
        self.assertEqual(merged, {})

    def test_wait_for_ready_opt_in_skips_when_no_config(self):
        page = MagicMock()
        result = _wait_for_ready(page, percy_config={}, kwargs={})
        self.assertIsNone(result)
        page.evaluate.assert_not_called()

    def test_wait_for_ready_runs_when_kwargs_opt_in(self):
        diagnostics = {'passed': True, 'preset': 'balanced'}
        page = MagicMock()
        page.evaluate.return_value = diagnostics

        result = _wait_for_ready(page, percy_config={}, kwargs={'readiness': {}})

        self.assertEqual(result, diagnostics)
        self.assertEqual(page.evaluate.call_count, 1)
        script, args = page.evaluate.call_args.args
        self.assertIn('PercyDOM.waitForReady', script)
        self.assertEqual(args[0], {})  # readiness config
        self.assertEqual(args[1], 12000)  # default deadline_ms (10000 + 2000)

    def test_wait_for_ready_runs_when_global_config_opts_in(self):
        page = MagicMock()
        page.evaluate.return_value = None
        percy_config = {'snapshot': {'readiness': {'preset': 'balanced'}}}

        _wait_for_ready(page, percy_config=percy_config, kwargs={})

        self.assertEqual(page.evaluate.call_count, 1)

    def test_wait_for_ready_skips_disabled_preset(self):
        page = MagicMock()
        result = _wait_for_ready(
            page, percy_config={}, kwargs={'readiness': {'preset': 'disabled'}})
        self.assertIsNone(result)
        page.evaluate.assert_not_called()

    def test_wait_for_ready_inlines_per_snapshot_config_into_args(self):
        page = MagicMock()
        page.evaluate.return_value = None
        cfg = {'preset': 'strict', 'stabilityWindowMs': 500}

        _wait_for_ready(page, percy_config={}, kwargs={'readiness': cfg})

        _, eval_args = page.evaluate.call_args.args
        self.assertEqual(eval_args[0], cfg)

    def test_wait_for_ready_honors_timeoutMs_for_deadline(self):
        page = MagicMock()
        page.evaluate.return_value = None

        _wait_for_ready(
            page, percy_config={},
            kwargs={'readiness': {'timeoutMs': 5000}})

        _, eval_args = page.evaluate.call_args.args
        # deadline_ms = timeoutMs + 2000
        self.assertEqual(eval_args[1], 7000)

    def test_wait_for_ready_swallows_exception_and_returns_none(self):
        page = MagicMock()
        page.evaluate.side_effect = RuntimeError('boom')

        with patch('percy.screenshot.log') as mock_log:
            result = _wait_for_ready(page, percy_config={}, kwargs={'readiness': {}})

        self.assertIsNone(result)
        mock_log.assert_called_once()
        self.assertIn('waitForReady failed', mock_log.call_args.args[0])

    def test_get_serialized_dom_skips_readiness_when_flag_set(self):
        """skip_readiness=True (responsive capture path) reuses the caller's
        diagnostics instead of running readiness again per width."""
        page = MagicMock()
        page.evaluate.return_value = {'html': '<html></html>'}
        page.url = 'http://localhost:8000/'
        page.frames = []
        page.context.return_value.cookies.return_value = []

        result = get_serialized_dom(
            page, cookies=[], percy_config={},
            skip_readiness=True,
            readiness_diagnostics={'cached': True},
        )

        # Diagnostics from caller propagated, _wait_for_ready never invoked
        self.assertEqual(result['readiness_diagnostics'], {'cached': True})
        # Only the serialize call hits evaluate
        evaluate_scripts = [c.args[0] for c in page.evaluate.call_args_list]
        self.assertFalse(any(
            isinstance(s, str) and 'waitForReady' in s for s in evaluate_scripts
        ))


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
            _is_percy_enabled(),
            {
                "session_type": "web",
                "config": {},
                "widths": {},
                "device_details": [],
            },
        )

        # Clear the cache to test the unsuccessful scenario
        _is_percy_enabled.cache_clear()

        # Mock unsuccessful health check
        mock_get.return_value.json.return_value = {"success": False, "error": "error"}
        self.assertFalse(_is_percy_enabled())

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
    @patch("percy.screenshot._is_percy_enabled")
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
    @patch("percy.screenshot._is_percy_enabled")
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

    def test_process_frame_returns_cors_iframe_data(self):
        page = MagicMock()
        page.evaluate.return_value = {"percyElementId": "iframe-1"}

        frame = MagicMock()
        frame.url = "http://cross-origin.example/frame"
        frame.evaluate.side_effect = [None, {"html": "<iframe></iframe>"}]

        result = process_frame(
            page,
            frame,
            {"enableJavaScript": False},
            "percy-dom-script"
        )

        self.assertEqual(
            result,
            {
                "iframeData": {"percyElementId": "iframe-1"},
                "iframeSnapshot": {"html": "<iframe></iframe>"},
                "frameUrl": "http://cross-origin.example/frame",
            },
        )

    def test_get_serialized_dom_adds_cors_iframes(self):
        page = MagicMock()
        page.url = "http://example.com"
        page.evaluate.return_value = {"html": "<html></html>"}

        same_origin_frame = MagicMock()
        same_origin_frame.url = "http://example.com/frame"
        cross_origin_frame = MagicMock()
        cross_origin_frame.url = "http://other.example/frame"
        page.frames = [same_origin_frame, cross_origin_frame]

        with patch("percy.screenshot.process_frame") as mock_process:
            mock_process.return_value = {"frameUrl": "http://other.example/frame"}
            dom_snapshot = get_serialized_dom(
                page,
                [{"name": "foo", "value": "bar"}],
                percy_dom_script="percy-dom"
            )

        mock_process.assert_called_once_with(page, cross_origin_frame, {}, "percy-dom")
        self.assertEqual(
            dom_snapshot["corsIframes"],
            [{"frameUrl": "http://other.example/frame"}]
        )
        self.assertEqual(
            dom_snapshot["cookies"],
            [{"name": "foo", "value": "bar"}]
        )

    def test_process_frame_returns_none_on_error(self):
        page = MagicMock()
        frame = MagicMock()
        frame.url = "http://cross-origin.example/frame"
        frame.evaluate.side_effect = Exception("boom")

        with patch("percy.screenshot.log") as mock_log:
            result = process_frame(page, frame, {}, "percy-dom-script")

        self.assertIsNone(result)
        mock_log.assert_called_once()

    def test_process_frame_returns_none_when_iframe_data_missing(self):
        page = MagicMock()
        page.evaluate.return_value = None  # iframe element not found on main page

        frame = MagicMock()
        frame.url = "http://cross-origin.example/frame"
        frame.evaluate.side_effect = [None, {"html": "<iframe></iframe>"}]

        with patch("percy.screenshot.log") as mock_log:
            result = process_frame(page, frame, {}, "percy-dom-script")

        self.assertIsNone(result)
        mock_log.assert_called_once_with(
            "Skipping cross-origin frame http://cross-origin.example/frame: "
            "no matching iframe element with percyElementId found on main page",
            "debug"
        )

    def test_process_frame_returns_none_when_percy_element_id_missing(self):
        page = MagicMock()
        page.evaluate.return_value = {}  # iframe found but lacks percyElementId

        frame = MagicMock()
        frame.url = "http://cross-origin.example/frame"
        frame.evaluate.side_effect = [None, {"html": "<iframe></iframe>"}]

        with patch("percy.screenshot.log") as mock_log:
            result = process_frame(page, frame, {}, "percy-dom-script")

        self.assertIsNone(result)
        mock_log.assert_called_once_with(
            "Skipping cross-origin frame http://cross-origin.example/frame: "
            "no matching iframe element with percyElementId found on main page",
            "debug"
        )

    def test_get_serialized_dom_skips_empty_cors_results(self):
        page = MagicMock()
        page.url = "http://example.com"
        page.evaluate.return_value = {"html": "<html></html>"}
        cross_origin_frame = MagicMock()
        cross_origin_frame.url = "http://other.example/frame"
        page.frames = [cross_origin_frame]

        with patch("percy.screenshot.process_frame") as mock_process:
            mock_process.return_value = None
            dom_snapshot = get_serialized_dom(
                page,
                [{"name": "foo", "value": "bar"}],
                percy_dom_script="percy-dom"
            )

        self.assertNotIn("corsIframes", dom_snapshot)
        self.assertEqual(
            dom_snapshot["cookies"],
            [{"name": "foo", "value": "bar"}]
        )

    def test_get_serialized_dom_logs_when_frame_processing_fails(self):
        class BadUrl:  # pylint: disable=too-few-public-methods
            def __str__(self):
                raise Exception("boom")

        page = MagicMock()
        page.url = BadUrl()
        page.evaluate.return_value = {"html": "<html></html>"}

        with patch("percy.screenshot.log") as mock_log:
            dom_snapshot = get_serialized_dom(
                page,
                [{"name": "foo", "value": "bar"}],
                percy_dom_script="percy-dom"
            )

        mock_log.assert_called_once()
        self.assertEqual(
            dom_snapshot["cookies"],
            [{"name": "foo", "value": "bar"}]
        )

    @patch("requests.post")
    @patch("percy.screenshot.capture_responsive_dom")
    @patch("percy.screenshot.fetch_percy_dom")
    @patch("percy.screenshot._is_percy_enabled")
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
            [{"name": "foo", "value": "bar"}],
            "some_js_code",
            config={"snapshot": {"responsiveSnapshotCapture": True}},
        )
        posted = mock_post.call_args.kwargs["json"]
        self.assertEqual(posted["dom_snapshot"], mock_capture_responsive_dom.return_value)

    @patch("requests.post")
    @patch("percy.screenshot._is_percy_enabled")
    def test_percy_automate_screenshot(self, mock_is_percy_enabled, mock_post):
        # Mock Percy enabled for automate
        _is_percy_enabled.cache_clear()
        mock_is_percy_enabled.return_value = {
            "session_type": "automate",
            "config": {},
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

    @patch("percy.screenshot._is_percy_enabled")
    def test_percy_automate_screenshot_percy_disabled(self, mock_is_percy_enabled):
        """Test percy_automate_screenshot when Percy is not enabled."""
        _is_percy_enabled.cache_clear()
        mock_is_percy_enabled.return_value = False

        page = MagicMock()
        result = percy_automate_screenshot(page, "screenshot_name")

        # Should return None when Percy is disabled
        self.assertIsNone(result)

    @patch("percy.screenshot._is_percy_enabled")
    def test_percy_automate_screenshot_invalid_call(self, mock_is_percy_enabled):
        # Mock Percy enabled for web
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {},
        }
        page = MagicMock()

        # Call the function and expect an exception
        with self.assertRaises(Exception) as context:
            percy_automate_screenshot(page, "screenshot_name")

        self.assertTrue("Invalid function call" in str(context.exception))

    @patch("requests.post")
    @patch("percy.screenshot._is_percy_enabled")
    def test_percy_automate_screenshot_with_options(self, mock_is_percy_enabled, mock_post):
        """Test percy_automate_screenshot when options are provided (not None)."""
        # Mock Percy enabled for automate
        _is_percy_enabled.cache_clear()
        mock_is_percy_enabled.return_value = {
            "session_type": "automate",
            "config": {},
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
        _is_percy_enabled.cache_clear()
        fetch_percy_dom.cache_clear()

    @patch("requests.get")
    def test_is_percy_enabled_request_error(self, mock_get):
        mock_get.side_effect = Exception("boom")
        with patch.object(local, "PERCY_DEBUG", True), patch("builtins.print") as mock_print:
            self.assertFalse(_is_percy_enabled())
            mock_print.assert_any_call(
                f"{LABEL} Percy is not running, disabling snapshots"
            )

    @patch("requests.get")
    def test_is_percy_enabled_raise_for_status(self, mock_get):
        mock_get.return_value.raise_for_status.side_effect = Exception("boom")
        mock_get.return_value.json.return_value = {"success": True}
        with patch.object(local, "PERCY_DEBUG", False):
            self.assertFalse(_is_percy_enabled())

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
        page.set_viewport_size.side_effect = PlaywrightError("boom")
        page.wait_for_function.side_effect = PlaywrightTimeoutError("boom")

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
            "percy.screenshot.get_responsive_widths"
        ) as mock_widths, patch(
            "percy.screenshot.get_serialized_dom"
        ) as mock_serialized, patch(
            "percy.screenshot.change_window_dimension_and_wait"
        ) as mock_resize:
            mock_widths.return_value = [{"width": 800, "height": 600}]
            mock_serialized.return_value = {"html": "<html></html>"}

            capture_responsive_dom(page, [{"name": "foo", "value": "bar"}])

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
            "percy.screenshot.get_responsive_widths"
        ) as mock_widths, patch(
            "percy.screenshot.get_serialized_dom"
        ) as mock_serialized, patch(
            "percy.screenshot.change_window_dimension_and_wait"
        ) as mock_resize:
            mock_widths.return_value = [{"width": 1024, "height": 768}]
            mock_serialized.return_value = {"html": "<html></html>"}

            capture_responsive_dom(page, [{"name": "foo", "value": "bar"}])

        page.evaluate.assert_any_call(
            "() => ({ width: window.innerWidth, height: window.innerHeight })"
        )
        mock_resize.assert_called_once_with(page, 1024, 768, 1)

    @patch("requests.post")
    @patch("percy.screenshot.fetch_percy_dom")
    @patch("percy.screenshot._is_percy_enabled")
    def test_percy_snapshot_response_error(
        self, mock_is_percy_enabled, mock_fetch_percy_dom, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {},
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
    @patch("percy.screenshot._is_percy_enabled")
    def test_percy_snapshot_request_error(
        self, mock_is_percy_enabled, mock_fetch_percy_dom, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "web",
            "config": {},
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
    @patch("percy.screenshot._is_percy_enabled")
    def test_percy_automate_screenshot_response_error(
        self, mock_is_percy_enabled, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "automate",
            "config": {},
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
    @patch("percy.screenshot._is_percy_enabled")
    def test_percy_automate_screenshot_request_error(
        self, mock_is_percy_enabled, mock_post
    ):
        mock_is_percy_enabled.return_value = {
            "session_type": "automate",
            "config": {},
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


# pylint: disable=too-many-public-methods
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
        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT", None):
            self.assertEqual(calculate_default_height(123), 123)

    def test_calculate_default_height_env_enabled(self):
        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT", "1"):
            self.assertEqual(calculate_default_height(123, min_height=200), 200)

    def test_calculate_default_height_env_enabled_handles_error(self):
        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT", "1"):
            self.assertEqual(calculate_default_height(321), 321)

    def test_calculate_default_height_uses_config_min_height(self):
        config = {"snapshot": {"minHeight": 500}}
        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT", "1"):
            self.assertEqual(calculate_default_height(321, config=config), 500)

    def test_calculate_default_height_uses_current_height_as_fallback(self):
        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT", "1"):
            self.assertEqual(calculate_default_height(321), 321)

    @patch("requests.get")
    def test_get_responsive_widths(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "widths": [
                {"width": 375, "height": 667},
                {"width": 1280, "height": 900},
            ]
        }

        widths = get_responsive_widths([375, 1280])

        self.assertEqual(
            widths,
            [
                {"width": 375, "height": 667},
                {"width": 1280, "height": 900},
            ],
        )
        mock_get.assert_called_once_with(
            "http://localhost:5338/percy/widths-config?widths=375,1280",
            timeout=30,
        )

    @patch("requests.get")
    def test_get_responsive_widths_missing_widths(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"widths": "not-a-list"}

        with self.assertRaises(Exception) as context:
            get_responsive_widths([800])

        self.assertEqual(
            str(context.exception),
            "Update Percy CLI to the latest version to use responsiveSnapshotCapture",
        )

    @patch("requests.get")
    def test_get_responsive_widths_with_none(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "widths": [
                {"width": 375, "height": 667},
            ]
        }

        widths = get_responsive_widths(None)

        self.assertEqual(
            widths,
            [
                {"width": 375, "height": 667},
            ],
        )
        mock_get.assert_called_once_with(
            "http://localhost:5338/percy/widths-config",
            timeout=30,
        )

    @patch("requests.get")
    def test_get_responsive_widths_with_empty_list(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "widths": [
                {"width": 375, "height": 667},
            ]
        }

        widths = get_responsive_widths([])

        self.assertEqual(
            widths,
            [
                {"width": 375, "height": 667},
            ],
        )
        mock_get.assert_called_once_with(
            "http://localhost:5338/percy/widths-config",
            timeout=30,
        )

    def test_capture_responsive_dom_calls_resize_reload_sleep(self):
        page = MagicMock()
        page.viewport_size = {"width": 800, "height": 600}
        page.evaluate = MagicMock()
        page.reload = MagicMock()

        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE", "1"), patch.object(
            local, "RESPONSIVE_CAPTURE_SLEEP_TIME", "1"
        ), patch(
            "percy.screenshot.get_responsive_widths"
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

            result = capture_responsive_dom(page, [{"name": "foo", "value": "bar"}], "dom-script")

        page.evaluate.assert_any_call("PercyDOM.waitForResize()")
        page.evaluate.assert_any_call("dom-script")
        self.assertEqual(page.evaluate.call_count, 5)
        self.assertEqual(page.reload.call_count, 2)
        mock_sleep.assert_any_call(1)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_resize.assert_has_calls(
            [
                call(page, 1200, 700, 1),
                call(page, 800, 600, 1),
            ]
        )
        self.assertEqual(result[0]["width"], 800)
        self.assertEqual(result[1]["width"], 1200)

    def test_capture_responsive_dom_invalid_sleep_time(self):
        page = MagicMock()
        page.viewport_size = {"width": 800, "height": 600}
        page.evaluate = MagicMock()
        page.reload = MagicMock()

        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE", None), patch.object(
            local, "RESPONSIVE_CAPTURE_SLEEP_TIME", "not-a-number"
        ), patch(
            "percy.screenshot.get_responsive_widths"
        ) as mock_widths, patch(
            "percy.screenshot.get_serialized_dom"
        ) as mock_serialized, patch(
            "percy.screenshot.change_window_dimension_and_wait"
        ), patch(
            "percy.screenshot.sleep"
        ) as mock_sleep:
            mock_widths.return_value = [{"width": 800, "height": 600}]
            mock_serialized.return_value = {"html": "<html></html>"}

            capture_responsive_dom(page, [])

        mock_sleep.assert_not_called()

    def test_capture_responsive_dom_zero_sleep_time(self):
        page = MagicMock()
        page.viewport_size = {"width": 800, "height": 600}
        page.evaluate = MagicMock()

        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE", None), patch.object(
            local, "RESPONSIVE_CAPTURE_SLEEP_TIME", "0"
        ), patch(
            "percy.screenshot.get_responsive_widths"
        ) as mock_widths, patch(
            "percy.screenshot.get_serialized_dom"
        ) as mock_serialized, patch(
            "percy.screenshot.change_window_dimension_and_wait"
        ), patch(
            "percy.screenshot.sleep"
        ) as mock_sleep:
            mock_widths.return_value = [{"width": 800, "height": 600}]
            mock_serialized.return_value = {"html": "<html></html>"}

            capture_responsive_dom(page, [])

        mock_sleep.assert_not_called()

    def test_capture_responsive_dom_skips_resize_for_same_width(self):
        """Test that resize is skipped when consecutive widths are the same."""
        page = MagicMock()
        page.viewport_size = {"width": 800, "height": 600}
        page.evaluate = MagicMock()

        with patch.object(local, "PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE", None), patch.object(
            local, "RESPONSIVE_CAPTURE_SLEEP_TIME", None
        ), patch(
            "percy.screenshot.get_responsive_widths"
        ) as mock_widths, patch(
            "percy.screenshot.get_serialized_dom"
        ) as mock_serialized, patch(
            "percy.screenshot.change_window_dimension_and_wait"
        ) as mock_resize:
            # Test with duplicate widths: 800 (same as viewport), 1200, 1200 (duplicate), 1400
            mock_widths.return_value = [
                {"width": 800, "height": 600},
                {"width": 1200, "height": 700},
                {"width": 1200, "height": 700},  # Duplicate - should not trigger resize
                {"width": 1400, "height": 800},
            ]
            mock_serialized.side_effect = [
                {"html": "<html></html>"},
                {"html": "<html></html>"},
                {"html": "<html></html>"},
                {"html": "<html></html>"},
            ]

            result = capture_responsive_dom(page, [])

        # Verify resize is called only when width changes:
        # 1. First width (800) matches viewport - no resize
        # 2. Second width (1200) differs - resize to 1200
        # 3. Third width (1200) same as previous - no resize
        # 4. Fourth width (1400) differs - resize to 1400
        # 5. Final restore to viewport (800) - resize to 800
        mock_resize.assert_has_calls(
            [
                call(page, 1200, 700, 1),  # First change from 800 to 1200
                call(page, 1400, 800, 2),  # Second change from 1200 to 1400
                call(page, 800, 600, 3),   # Final restore
            ]
        )
        self.assertEqual(mock_resize.call_count, 3)
        self.assertEqual(len(result), 4)  # All 4 widths should have snapshots

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
