import os
import json
import platform
from functools import lru_cache
from time import sleep
import requests

from playwright._repo_version import version as PLAYWRIGHT_VERSION
from percy.version import __version__ as SDK_VERSION
from percy.page_metadata import PageMetaData

# Collect client environment information
CLIENT_INFO = "percy-playwright-python/" + SDK_VERSION
ENV_INFO = ["playwright/" + PLAYWRIGHT_VERSION, "python/" + platform.python_version()]

# Maybe get the CLI API address from the environment
PERCY_CLI_API = os.environ.get("PERCY_CLI_API") or "http://localhost:5338"
PERCY_DEBUG = os.environ.get("PERCY_LOGLEVEL") == "debug"
RESPONSIVE_CAPTURE_SLEEP_TIME = os.environ.get("RESPONSIVE_CAPTURE_SLEEP_TIME")
PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT = os.environ.get("PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT")
PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE = os.environ.get("PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE")

# for logging
LABEL = "[\u001b[35m" + ("percy:python" if PERCY_DEBUG else "percy") + "\u001b[39m]"

def log(message, lvl="info"):
    message = f"{LABEL} {message}"
    try:
        requests.post(
            f"{PERCY_CLI_API}/percy/log",
            json={"message": message, "level": lvl},
            timeout=1,
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
def is_percy_enabled():
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


def get_serialized_dom(page, cookies, **kwargs):
    dom_snapshot = page.evaluate(f"PercyDOM.serialize({json.dumps(kwargs)})")
    dom_snapshot["cookies"] = cookies
    return dom_snapshot


def calculate_default_height(page, current_height, **kwargs):
    """Calculate default height for responsive capture."""
    if not PERCY_RESPONSIVE_CAPTURE_MIN_HEIGHT:
        return current_height

    try:
        min_height = kwargs.get("min_height") or current_height
        return page.evaluate(
            "(minH) => window.outerHeight - window.innerHeight + minH", min_height
        )
    except Exception:
        return current_height


def get_widths_for_multi_dom(eligible_widths, device_details, default_height, **kwargs):
    user_passed_widths = kwargs.get("widths", [])
    width = kwargs.get("width")
    if width:
        user_passed_widths = [width]

    width_height_map = {}

    # Add mobile widths with their associated heights from device_details (if available)
    mobile_widths = eligible_widths.get("mobile", [])
    if len(mobile_widths) != 0:
        for mobile_width in mobile_widths:
            if mobile_width not in width_height_map:
                device_info = next(
                    (device for device in device_details if device.get("width") == mobile_width),
                    None,
                )
                width_height_map[mobile_width] = {
                    "width": mobile_width,
                    "height": device_info.get("height", default_height)
                    if device_info
                    else default_height,
                }

    # Add user passed or config widths with default height
    other_widths = (
        user_passed_widths if len(user_passed_widths) != 0 else eligible_widths.get("config", [])
    )
    for w in other_widths:
        if w not in width_height_map:
            width_height_map[w] = {"width": w, "height": default_height}

    return list(width_height_map.values())


def change_window_dimension_and_wait(page, width, height, resize_count):
    try:
        page.set_viewport_size({"width": width, "height": height})
    except Exception as e:
        log(f"Resizing viewport failed for width {width}: {e}", "debug")

    try:
        page.wait_for_function(
            f"window.resizeCount === {resize_count}", timeout=1000
        )
    except Exception:
        log(f"Timed out waiting for window resize event for width {width}", "debug")


def capture_responsive_dom(page, eligible_widths, device_details, cookies, **kwargs):
    current_width = page.viewport_size["width"]
    current_height = page.viewport_size["height"]
    default_height = calculate_default_height(page, current_height, **kwargs)

    # Get width and height combinations
    width_heights = get_widths_for_multi_dom(
        eligible_widths, device_details, default_height, **kwargs
    )

    dom_snapshots = []
    last_window_width = current_width
    resize_count = 0
    page.evaluate("PercyDOM.waitForResize()")

    for width_height in width_heights:
        if last_window_width != width_height["width"]:
            resize_count += 1
            change_window_dimension_and_wait(
                page, width_height["width"], width_height["height"], resize_count
            )
            last_window_width = width_height["width"]

        if PERCY_RESPONSIVE_CAPTURE_RELOAD_PAGE:
            page.reload()
            page.evaluate(fetch_percy_dom())

        if RESPONSIVE_CAPTURE_SLEEP_TIME:
            sleep(int(RESPONSIVE_CAPTURE_SLEEP_TIME))
        dom_snapshot = get_serialized_dom(page, cookies, **kwargs)
        dom_snapshot["width"] = width_height["width"]
        dom_snapshots.append(dom_snapshot)

    change_window_dimension_and_wait(
        page, current_width, current_height, resize_count + 1
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
    data = is_percy_enabled()
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
        page.evaluate(fetch_percy_dom())
        cookies = page.context.cookies()

        # Serialize and capture the DOM
        if is_responsive_snapshot_capture(data["config"], **kwargs):
            dom_snapshot = capture_responsive_dom(
                page, data["widths"], data["device_details"], cookies, **kwargs
            )
        else:
            dom_snapshot = get_serialized_dom(page, cookies, **kwargs)

        # Post the DOM to the snapshot endpoint with snapshot options and other info
        response = requests.post(
            f"{PERCY_CLI_API}/percy/snapshot",
            json={
                **kwargs,
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
    data = is_percy_enabled()
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
