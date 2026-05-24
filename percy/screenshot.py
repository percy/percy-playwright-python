import os
import json
import platform
from functools import lru_cache
from time import sleep
from urllib.parse import urlparse
import requests

from playwright._repo_version import version as PLAYWRIGHT_VERSION
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from percy.version import __version__ as SDK_VERSION
from percy.page_metadata import PageMetaData

# Collect client environment information
CLIENT_INFO = "percy-playwright-python/" + SDK_VERSION
ENV_INFO = ["playwright/" + PLAYWRIGHT_VERSION, "python/" + platform.python_version()]

def _get_bool_env(key):
    """Get boolean value from environment variable."""
    return os.environ.get(key, "").lower() == "true"

# Maybe get the CLI API address from the environment
PERCY_CLI_API = os.environ.get("PERCY_CLI_API") or "http://localhost:5338"
PERCY_DEBUG = os.environ.get("PERCY_LOGLEVEL") == "debug"
RESPONSIVE_CAPTURE_SLEEP_TIME = os.environ.get("RESPONSIVE_CAPTURE_SLEEP_TIME")
PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT = _get_bool_env("PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT")
PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE = _get_bool_env("PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE")

# for logging
LABEL = "[\u001b[35m" + ("percy:python" if PERCY_DEBUG else "percy") + "\u001b[39m]"

def log(message, lvl="info"):
    message = f"{LABEL} {message}"
    try:
        requests.post(
            f"{PERCY_CLI_API}/percy/log",
            json={"message": message, "level": lvl},
            timeout=5,
        )
    except Exception as e:
        if PERCY_DEBUG:
            print(f"Sending log to CLI Failed {e}")
    finally:
        # Only log if lvl is 'debug' and PERCY_DEBUG is True
        if lvl != "debug" or PERCY_DEBUG:
            print(message)


# Check if Percy is enabled, caching the result so it is only checked once
@lru_cache(maxsize=None)
def _is_percy_enabled():
    try:
        response = requests.get(f"{PERCY_CLI_API}/percy/healthcheck", timeout=30)
        response.raise_for_status()
        data = response.json()
        session_type = data.get("type", None)
        widths = data.get("widths", {})
        config = data.get("config", {})
        device_details = data.get("deviceDetails", [])

        if not data["success"]:
            raise Exception(data["error"])
        version = response.headers.get("x-percy-core-version")

        if not version:
            print(
                f"{LABEL} You may be using @percy/agent "
                "which is no longer supported by this SDK. "
                "Please uninstall @percy/agent and install @percy/cli instead. "
                "https://www.browserstack.com/docs/percy/migration/migrate-to-cli"
            )
            return False

        if version.split(".")[0] != "1":
            print(f"{LABEL} Unsupported Percy CLI version, {version}")
            return False

        return {
            "session_type": session_type,
            "config": config,
            "widths": widths,
            "device_details": device_details,
        }
    except Exception as e:
        print(f"{LABEL} Percy is not running, disabling snapshots")
        if PERCY_DEBUG:
            print(f"{LABEL} {e}")
        return False


# Fetch the @percy/dom script, caching the result so it is only fetched once
@lru_cache(maxsize=None)
def fetch_percy_dom():
    response = requests.get(f"{PERCY_CLI_API}/percy/dom.js", timeout=30)
    response.raise_for_status()
    return response.text


def process_frame(page, frame, options, percy_dom_script):
    """
    Processes a single cross-origin frame to capture its snapshot and resources.

    Args:
        page: The main page object
        frame: The frame to process
        options: Snapshot options
        percy_dom_script: The Percy DOM serialization script

    Returns:
        Dictionary containing iframe data, snapshot, and URL
    """
    frame_url = frame.url

    try:
        # Inject Percy DOM into the cross-origin frame
        frame.evaluate(percy_dom_script)

        # enableJavaScript=True prevents the standard iframe serialization logic from running.
        # This is necessary because we're manually handling cross-origin iframe serialization here.
        iframe_snapshot = frame.evaluate(
            f"PercyDOM.serialize({json.dumps({**options, 'enableJavaScript': True})})"
        )

        # Get the iframe's element data from the main page context
        iframe_data = page.evaluate(
            """(fUrl) => {
                const iframes = Array.from(document.querySelectorAll('iframe'));
                const matchingIframe = iframes.find(iframe => iframe.src.startsWith(fUrl));
                if (matchingIframe) {
                    return {
                        percyElementId: matchingIframe.getAttribute('data-percy-element-id')
                    };
                }
            }""",
            frame_url
        )

        if not iframe_data or not iframe_data.get("percyElementId"):
            log(
                f"Skipping cross-origin frame {frame_url}: "
                "no matching iframe element with percyElementId found on main page",
                "debug"
            )
            return None

        return {
            "iframeData": iframe_data,
            "iframeSnapshot": iframe_snapshot,
            "frameUrl": frame_url
        }
    except Exception as e:
        log(f"Failed to process cross-origin frame {frame_url}: {e}", "debug")
        return None


def _resolve_readiness_config(percy_config, kwargs):
    """Shallow-merge global (percy_config.snapshot.readiness) and per-snapshot
    (kwargs['readiness']) readiness config. Per-snapshot keys win; unspecified
    keys (e.g. a global preset: disabled kill switch) are inherited.

    Defensive: `(config or {}).get('snapshot') or {}` guards against the CLI
    returning a None-valued snapshot section."""
    config = percy_config or {}
    global_readiness = ((config.get('snapshot') or {}).get('readiness')) or {}
    per_snapshot = kwargs.get('readiness') or {}
    if not isinstance(global_readiness, dict):
        global_readiness = {}
    if not isinstance(per_snapshot, dict):
        per_snapshot = {}
    return {**global_readiness, **per_snapshot}


def _wait_for_ready(page, percy_config, kwargs):
    """Run readiness checks before serialize. PER-7348.

    Uses page.evaluate (sync Playwright auto-awaits Promises). The embedded
    JS checks typeof PercyDOM.waitForReady === 'function' so old CLI versions
    without the method are a graceful no-op.

    Returns readiness diagnostics dict (or None) to be attached to the
    domSnapshot. Callers pass `percy_config` explicitly from the
    `_is_percy_enabled()` payload they already have in scope — we don't
    re-call the cached lookup here, both for clarity and to avoid surprise
    dependencies on the cache.
    """
    readiness_config = _resolve_readiness_config(percy_config, kwargs)
    if readiness_config.get('preset') == 'disabled':
        return None
    # Hard JS-side timeout: even though Playwright auto-awaits Promises, a
    # waitForReady() that never resolves (e.g. CLI's internal observers
    # keep ticking) would block the whole snapshot suite. Race against a
    # Promise that resolves after the readiness deadline + 2s buffer.
    timeout_ms = readiness_config.get('timeoutMs')
    deadline_ms = int((timeout_ms if isinstance(timeout_ms, (int, float)) and timeout_ms > 0
                       else 10000) + 2000)
    try:
        return page.evaluate(
            "([cfg, deadlineMs]) => {"
            "  if (typeof PercyDOM === 'undefined'"
            "      || typeof PercyDOM.waitForReady !== 'function') {"
            "    return null;"
            "  }"
            "  return Promise.race(["
            "    PercyDOM.waitForReady(cfg),"
            "    new Promise(resolve => setTimeout(resolve, deadlineMs))"
            "  ]);"
            "}",
            [readiness_config, deadline_ms],
        )
    except Exception as e:
        log(f'waitForReady failed, proceeding to serialize: {e}', 'debug')
        return None


# pylint: disable=too-many-locals
def get_serialized_dom(page, cookies, percy_dom_script=None, *,
                       percy_config=None, skip_readiness=False,
                       readiness_diagnostics=None, **kwargs):
    """
    Serializes the DOM and captures cross-origin iframes.

    Args:
        page: The page object
        cookies: Page cookies
        percy_config: CLI healthcheck config (used for readiness merge)
        percy_dom_script: The Percy DOM serialization script
        skip_readiness: Set True when the caller has already run readiness
            once (e.g. responsive capture running it before the width loop)
            to avoid paying the cost per width.
        readiness_diagnostics: Diagnostics from the caller's earlier
            readiness run, used when skip_readiness=True.
        **kwargs: Additional options

    Returns:
        Dictionary containing the DOM snapshot with cross-origin iframe data
    """
    # Readiness gate before serialize (PER-7348). Graceful on old CLI.
    if not skip_readiness:
        readiness_diagnostics = _wait_for_ready(page, percy_config, kwargs)
    # Strip `readiness` from forwarded serialize args — it's consumed by
    # _wait_for_ready upstream, not a PercyDOM.serialize argument.
    serialize_kwargs = {k: v for k, v in kwargs.items() if k != 'readiness'}
    dom_snapshot = page.evaluate(f"PercyDOM.serialize({json.dumps(serialize_kwargs)})")
    # Attach readiness diagnostics so the CLI can log timing and pass/fail.
    # `is not None` preserves legitimate falsy returns like {} ("gate ran,
    # no notable diagnostics").
    if readiness_diagnostics is not None and isinstance(dom_snapshot, dict):
        dom_snapshot['readiness_diagnostics'] = readiness_diagnostics

    # Process CORS IFrames
    # Note: Blob URL handling (data-src images, blob background images) is now handled
    # in the CLI via async DOM serialization. This section only handles cross-origin
    # iframe serialization and resource merging.
    try:
        page_url = urlparse(page.url)
        frames = page.frames

        # Filter for cross-origin frames (excluding about:blank)
        cross_origin_frames = [
            frame for frame in frames
            if frame.url != "about:blank" and urlparse(frame.url).netloc != page_url.netloc
        ]

        if cross_origin_frames and percy_dom_script:
            processed_frames = []
            for frame in cross_origin_frames:
                result = process_frame(page, frame, kwargs, percy_dom_script)
                if result:
                    processed_frames.append(result)

            if processed_frames:
                dom_snapshot["corsIframes"] = processed_frames
    except Exception as e:
        log(f"Failed to process cross-origin iframes: {e}", "debug")

    dom_snapshot["cookies"] = cookies
    return dom_snapshot


# pylint: disable=too-many-arguments, too-many-branches
def create_region(
    boundingBox=None,
    elementXpath=None,
    elementCSS=None,
    padding=None,
    algorithm="ignore",
    diffSensitivity=None,
    imageIgnoreThreshold=None,
    carouselsEnabled=None,
    bannersEnabled=None,
    adsEnabled=None,
    diffIgnoreThreshold=None
    ):

    element_selector = {}
    if boundingBox:
        element_selector["boundingBox"] = boundingBox
    if elementXpath:
        element_selector["elementXpath"] = elementXpath
    if elementCSS:
        element_selector["elementCSS"] = elementCSS

    region = {
        "algorithm": algorithm,
        "elementSelector": element_selector
    }

    if padding:
        region["padding"] = padding

    configuration = {}
    if algorithm in ["standard", "intelliignore"]:
        if diffSensitivity is not None:
            configuration["diffSensitivity"] = diffSensitivity
        if imageIgnoreThreshold is not None:
            configuration["imageIgnoreThreshold"] = imageIgnoreThreshold
        if carouselsEnabled is not None:
            configuration["carouselsEnabled"] = carouselsEnabled
        if bannersEnabled is not None:
            configuration["bannersEnabled"] = bannersEnabled
        if adsEnabled is not None:
            configuration["adsEnabled"] = adsEnabled

    if configuration:
        region["configuration"] = configuration

    assertion = {}
    if diffIgnoreThreshold is not None:
        assertion["diffIgnoreThreshold"] = diffIgnoreThreshold

    if assertion:
        region["assertion"] = assertion

    return region



def calculate_default_height(current_height, config=None, **kwargs):
    """Calculate default height for responsive capture."""
    if not PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT:
        return current_height

    config_min_height = (config or {}).get("snapshot", {}).get("minHeight")
    min_height = kwargs.get("min_height") or config_min_height or current_height
    return min_height


def get_responsive_widths(widths=None):
    """Gets computed responsive widths from the Percy server for responsive snapshot capture."""
    if widths is None:
        widths = []
    try:
        # Ensure widths is a list
        widths_list = widths if isinstance(widths, list) else []
        query_param = f"?widths={','.join(map(str, widths_list))}" if widths_list else ""
        response = requests.get(
            f"{PERCY_CLI_API}/percy/widths-config{query_param}",
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        widths_data = data.get("widths")
        if not isinstance(widths_data, list):
            msg = "Update Percy CLI to the latest version to use responsiveSnapshotCapture"
            raise Exception(msg)
        return widths_data
    except Exception as e:
        log(f"Failed to get responsive widths: {e}.", "debug")
        msg = "Update Percy CLI to the latest version to use responsiveSnapshotCapture"
        raise Exception(msg) from e


def _responsive_sleep():
    """Sleep for the configured responsive capture sleep time if positive."""
    if not RESPONSIVE_CAPTURE_SLEEP_TIME:
        return
    try:
        if (secs := int(RESPONSIVE_CAPTURE_SLEEP_TIME)) > 0:
            sleep(secs)
    except (TypeError, ValueError):
        pass


def change_window_dimension_and_wait(page, width, height, resize_count):
    try:
        page.set_viewport_size({"width": width, "height": height})
    except PlaywrightError as e:
        log(f"Resizing viewport failed for width {width}: {e}", "debug")

    try:
        page.wait_for_function(
            f"window.resizeCount === {resize_count}", timeout=1000
        )
    except PlaywrightTimeoutError:
        log(f"Timed out waiting for window resize event for width {width}", "debug")


# pylint: disable=too-many-locals
def capture_responsive_dom(page, cookies, percy_dom_script=None, config=None, **kwargs):
    viewport = page.viewport_size or page.evaluate(
        "() => ({ width: window.innerWidth, height: window.innerHeight })"
    )
    default_height = calculate_default_height(viewport["height"], config=config, **kwargs)

    # Get width and height combinations from CLI
    width_heights = get_responsive_widths(kwargs.get("widths", []))

    dom_snapshots = []
    last_window_width = viewport["width"]
    resize_count = 0
    page.evaluate("PercyDOM.waitForResize()")
    # Run readiness ONCE before the per-width loop. Running it per width can
    # cost up to N*timeoutMs of sequential waits — almost never the intent.
    responsive_readiness_diagnostics = _wait_for_ready(page, config, kwargs)

    for width_height in width_heights:
        # Apply default height if not provided by CLI
        height = width_height.get("height") or default_height
        width = width_height["width"]
        if last_window_width != width:
            resize_count += 1
            change_window_dimension_and_wait(
                page, width, height, resize_count
            )
            last_window_width = width

        if PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE:
            page.reload()
            page.evaluate(percy_dom_script)
            page.evaluate("PercyDOM.waitForResize()")
            resize_count = 0

        _responsive_sleep()
        snapshot = get_serialized_dom(
            page, cookies, percy_dom_script,
            percy_config=config,
            skip_readiness=True,
            readiness_diagnostics=responsive_readiness_diagnostics,
            **kwargs)
        snapshot["width"] = width
        dom_snapshots.append(snapshot)

    change_window_dimension_and_wait(
        page, viewport["width"], viewport["height"], resize_count + 1
    )
    return dom_snapshots


def is_responsive_snapshot_capture(config, **kwargs):
    # Don't run responsive snapshot capture when defer uploads is enabled
    if "percy" in config and config["percy"].get("deferUploads", False):
        return False

    return (
        kwargs.get("responsive_snapshot_capture", False)
        or kwargs.get("responsiveSnapshotCapture", False)
        or (
            "snapshot" in config
            and config["snapshot"].get("responsiveSnapshotCapture")
        )
    )


# Take a DOM snapshot and post it to the snapshot endpoint
def percy_snapshot(page, name, **kwargs):
    data = _is_percy_enabled()
    if not data:
        return None

    if data["session_type"] == "automate":
        raise Exception(
            "Invalid function call - "
            "percy_snapshot(). "
            "Please use percy_screenshot() function while using Percy with Automate. "
            "For more information on usage of PercyScreenshot, "
            "refer https://www.browserstack.com/docs/percy/integrate/functional-and-visual"
        )

    try:
        # Inject the DOM serialization script
        percy_dom_script = fetch_percy_dom()
        page.evaluate(percy_dom_script)
        cookies = page.context.cookies()

        # Serialize and capture the DOM
        if is_responsive_snapshot_capture(data["config"], **kwargs):
            dom_snapshot = capture_responsive_dom(
                page, cookies, percy_dom_script, config=data["config"], **kwargs
            )
        else:
            dom_snapshot = get_serialized_dom(
                page, cookies, percy_dom_script,
                percy_config=data.get("config"), **kwargs)

        # Strip `readiness` from POST body — SDK-local config that the CLI
        # already has via healthcheck.
        post_kwargs = {k: v for k, v in kwargs.items() if k != "readiness"}
        # Post the DOM to the snapshot endpoint with snapshot options and other info
        response = requests.post(
            f"{PERCY_CLI_API}/percy/snapshot",
            json={
                **post_kwargs,
                **{
                    "client_info": CLIENT_INFO,
                    "environment_info": ENV_INFO,
                    "dom_snapshot": dom_snapshot,
                    "url": page.url,
                    "name": name,
                },
            },
            timeout=600,
        )

        # Handle errors
        response.raise_for_status()
        response_data = response.json()

        if not response_data["success"]:
            raise Exception(response_data["error"])
        return response_data.get("data", None)
    except Exception as e:
        log(f'Could not take DOM snapshot "{name}"')
        log(f"{e}")
        return None


def percy_automate_screenshot(page, name, options=None, **kwargs):
    data = _is_percy_enabled()
    if not data:
        return None

    if data["session_type"] == "web":
        raise Exception(
            "Invalid function call - "
            "percy_screenshot(). Please use percy_snapshot() function for taking screenshot. "
            "percy_screenshot() should be used only while using Percy with Automate. "
            "For more information on usage of percy_snapshot(), "
            "refer doc for your language https://www.browserstack.com/docs/percy/integrate/overview"
        )

    if options is None:
        options = {}

    try:
        metadata = PageMetaData(page)

        # Post to automateScreenshot endpoint with page options and other info
        response = requests.post(
            f"{PERCY_CLI_API}/percy/automateScreenshot",
            json={
                **kwargs,
                **{
                    "client_info": CLIENT_INFO,
                    "environment_info": ENV_INFO,
                    "sessionId": metadata.automate_session_id,
                    "pageGuid": metadata.page_guid,
                    "frameGuid": metadata.frame_guid,
                    "framework": metadata.framework,
                    "snapshotName": name,
                    "options": options,
                },
            },
            timeout=600,
        )

        # Handle errors
        response.raise_for_status()
        response_data = response.json()

        if not response_data["success"]:
            raise Exception(response_data["error"])

        return response_data.get("data", None)
    except Exception as e:
        log(f'Could not take Screenshot "{name}"')
        log(f"{e}")
        return None
