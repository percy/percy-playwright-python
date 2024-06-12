import os
import json
import platform
from functools import lru_cache
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

# for logging
LABEL = "[\u001b[35m" + ("percy:python" if PERCY_DEBUG else "percy") + "\u001b[39m]"


# Check if Percy is enabled, caching the result so it is only checked once
@lru_cache(maxsize=None)
def is_percy_enabled():
    try:
        response = requests.get(f"{PERCY_CLI_API}/percy/healthcheck", timeout=30)
        response.raise_for_status()
        data = response.json()
        session_type = data.get("type", None)

        if not data["success"]:
            raise Exception(data["error"])
        version = response.headers.get("x-percy-core-version")

        if not version:
            print(
                f"{LABEL} You may be using @percy/agent "
                "which is no longer supported by this SDK. "
                "Please uninstall @percy/agent and install @percy/cli instead. "
                "https://docs.percy.io/docs/migrating-to-percy-cli"
            )
            return False

        if version.split(".")[0] != "1":
            print(f"{LABEL} Unsupported Percy CLI version, {version}")
            return False

        return session_type
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


# Take a DOM snapshot and post it to the snapshot endpoint
def percy_snapshot(page, name, **kwargs):
    session_type = is_percy_enabled()
    if session_type is False:
        return None  # Since session_type can be None for old CLI version
    if session_type == "automate":
        raise Exception(
            "Invalid function call - "
            "percy_snapshot()."
            "Please use percy_screenshot() function while using Percy with Automate. "
            "For more information on usage of PercyScreenshot, "
            "refer https://docs.percy.io/docs/integrate-functional-testing-with-visual-testing"
        )

    try:
        # Inject the DOM serialization script
        # print(fetch_percy_dom())
        page.evaluate(fetch_percy_dom())

        # Serialize and capture the DOM
        dom_snapshot_script = f"PercyDOM.serialize({json.dumps(kwargs)})"

        # Return the serialized DOM Snapshot
        dom_snapshot = page.evaluate(dom_snapshot_script)

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
        data = response.json()

        if not data["success"]:
            raise Exception(data["error"])
        return data.get("data", None)
    except Exception as e:
        print(f'{LABEL} Could not take DOM snapshot "{name}"')
        print(f"{LABEL} {e}")
        return None


def percy_automate_screenshot(page, name, options=None, **kwargs):
    session_type = is_percy_enabled()
    if session_type is False:
        return None  # Since session_type can be None for old CLI version
    if session_type == "web":
        raise Exception(
            "Invalid function call - "
            "percy_screenshot(). Please use percy_snapshot() function for taking screenshot. "
            "percy_screenshot() should be used only while using Percy with Automate. "
            "For more information on usage of percy_snapshot(), "
            "refer doc for your language https://docs.percy.io/docs/end-to-end-testing"
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
        data = response.json()

        if not data["success"]:
            raise Exception(data["error"])

        return data.get("data", None)
    except Exception as e:
        print(f'{LABEL} Could not take Screenshot "{name}"')
        print(f"{LABEL} {e}")
        return None
