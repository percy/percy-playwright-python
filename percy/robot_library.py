"""Robot Framework library for Percy visual testing with Playwright.

Provides keywords to capture Percy snapshots from Robot Framework tests
using the Browser library (robotframework-browser) as the Playwright backend.
All robot-specific imports are wrapped in try/except for graceful degradation
when robotframework is not installed.

Usage in Robot Framework:
    *** Settings ***
    Library    Browser
    Library    percy.robot_library.PercyLibrary

    *** Test Cases ***
    Homepage Visual Test
        New Browser    chromium    headless=true
        New Page    https://example.com
        Percy Snapshot    Homepage
        Close Browser

Run with:
    percy exec -- robot tests/
"""

import json

try:
    from robot.api.deco import keyword, library
    from robot.libraries.BuiltIn import BuiltIn
    ROBOT_AVAILABLE = True
except ImportError:
    ROBOT_AVAILABLE = False

# Lazy imports — percy.screenshot requires playwright at import time,
# so we defer the import to when keywords are actually called.
_screenshot_module = None

def _get_screenshot_module():
    global _screenshot_module  # pylint: disable=global-statement
    if _screenshot_module is None:
        from percy import screenshot as _mod  # pylint: disable=import-outside-toplevel
        _screenshot_module = _mod
    return _screenshot_module


def _parse_bool(val):
    if val is None:
        return None
    return str(val).lower() in ("true", "1", "yes")


def _parse_widths(widths):
    if not widths:
        return None
    if isinstance(widths, str):
        return [int(w.strip()) for w in widths.split(",")]
    if isinstance(widths, list):
        return [int(w) for w in widths]
    return None


def _parse_csv(val):
    if not val:
        return None
    if isinstance(val, str):
        return [v.strip() for v in val.split(",")]
    if isinstance(val, list):
        return val
    return None


def _parse_json(val):
    if not val:
        return None
    if isinstance(val, str):
        return json.loads(val)
    if isinstance(val, (dict, list)):
        return val
    return None


class _BrowserLibraryPageAdapter:
    """Adapter to make Browser library (robotframework-browser) look like a Playwright page.

    Percy's playwright SDK expects a Playwright page object with methods like
    evaluate(), url, and content(). This adapter bridges the gap by calling
    Browser library keywords via Robot Framework's BuiltIn.
    """

    @property
    def url(self):
        return BuiltIn().run_keyword("Browser.Get Url")

    def evaluate(self, expression):
        return BuiltIn().run_keyword("Browser.Evaluate JavaScript", "", expression)

    def content(self):
        return BuiltIn().run_keyword("Browser.Get Page Source")


if ROBOT_AVAILABLE:

    @library(scope="GLOBAL")
    class PercyLibrary:
        """Percy visual testing library for Robot Framework (Playwright/Browser backend).

        Provides keywords to capture visual snapshots using Percy.
        Requires Browser library (robotframework-browser) to be imported.

        Tests must be run under ``percy exec``:
        | percy exec -- robot tests/
        """

        def _get_page(self):
            """Get a page adapter for the Browser library."""
            try:
                BuiltIn().get_library_instance("Browser")
                return _BrowserLibraryPageAdapter()
            except RuntimeError as exc:
                raise RuntimeError(
                    "PercyLibrary requires Browser library to be imported"
                ) from exc

        # --------------------------------------------------------------
        # Percy Snapshot
        # --------------------------------------------------------------

        @keyword("Percy Snapshot")
        def percy_snapshot_keyword(  # pylint: disable=too-many-arguments,too-many-locals
            self, name, widths=None, min_height=None,
            percy_css=None, scope=None, scope_options=None,
            enable_javascript=None, enable_layout=None,
            disable_shadow_dom=None, labels=None,
            test_case=None, sync=None, regions=None,
            responsive_snapshot_capture=None,
        ):
            """Capture a Percy visual snapshot of the current page.

            ``name`` is the snapshot name shown in the Percy dashboard.

            ``widths`` is a comma-separated string of responsive widths
            (e.g., ``375,768,1280``).

            ``min_height`` is the minimum screenshot height in pixels.

            ``percy_css`` is custom CSS injected before the snapshot.

            ``scope`` is a CSS selector to limit the snapshot area.

            ``enable_javascript`` enables JS execution in Percy rendering.

            ``enable_layout`` enables layout comparison mode.

            ``labels`` is a comma-separated string of tags/labels.

            ``regions`` is a JSON string of region definitions.

            ``responsive_snapshot_capture`` enables responsive capture mode.

            Examples:
            | Percy Snapshot    Homepage
            | Percy Snapshot    Login    widths=375,1280    min_height=1024
            | Percy Snapshot    Dashboard    labels=dashboard,admin    enable_layout=True
            """
            page = self._get_page()
            mod = _get_screenshot_module()
            mod.percy_snapshot(
                page,
                name,
                widths=_parse_widths(widths),
                min_height=int(min_height) if min_height else None,
                percy_css=percy_css,
                scope=scope,
                scope_options=_parse_json(scope_options),
                enable_javascript=_parse_bool(enable_javascript),
                enable_layout=_parse_bool(enable_layout),
                disable_shadow_dom=_parse_bool(disable_shadow_dom),
                labels=",".join(_parse_csv(labels)) if labels else None,
                test_case=test_case,
                sync=_parse_bool(sync),
                regions=_parse_json(regions),
                responsive_snapshot_capture=_parse_bool(responsive_snapshot_capture),
            )

        # --------------------------------------------------------------
        # Region helpers
        # --------------------------------------------------------------

        @keyword("Create Percy Region")
        def create_percy_region_keyword(  # pylint: disable=too-many-arguments
            self, algorithm="ignore",
            bounding_box=None, element_xpath=None,
            element_css=None, padding=None,
            diff_sensitivity=None,
            image_ignore_threshold=None,
            carousels_enabled=None,
            banners_enabled=None, ads_enabled=None,
            diff_ignore_threshold=None,
        ):
            """Create a region definition for Percy ignore/consider regions.

            ``algorithm`` is one of ``ignore``, ``standard``, or ``intelliignore``.

            ``element_css`` is a CSS selector for the region.

            ``element_xpath`` is an XPath selector for the region.

            ``bounding_box`` is a JSON string with x, y, width, height.

            Returns a region dict to pass to ``Percy Snapshot`` via ``regions``.

            Examples:
            | ${region}=    Create Percy Region    algorithm=ignore    element_css=.ad-banner
            """
            mod = _get_screenshot_module()
            return mod.create_region(
                boundingBox=_parse_json(bounding_box),
                elementXpath=element_xpath,
                elementCSS=element_css,
                padding=int(padding) if padding else None,
                algorithm=algorithm,
                diffSensitivity=int(diff_sensitivity) if diff_sensitivity else None,
                imageIgnoreThreshold=(
                    float(image_ignore_threshold) if image_ignore_threshold else None
                ),
                carouselsEnabled=_parse_bool(carousels_enabled),
                bannersEnabled=_parse_bool(banners_enabled),
                adsEnabled=_parse_bool(ads_enabled),
                diffIgnoreThreshold=float(diff_ignore_threshold) if diff_ignore_threshold else None,
            )

        # --------------------------------------------------------------
        # Utility
        # --------------------------------------------------------------

        @keyword("Percy Is Running")
        def percy_is_running_keyword(self):
            """Check if the Percy CLI server is running.

            Returns ``True`` if Percy is available, ``False`` otherwise.
            """
            mod = _get_screenshot_module()
            return bool(mod._is_percy_enabled())  # pylint: disable=protected-access

else:
    class PercyLibrary:  # pylint: disable=function-redefined,too-few-public-methods
        """Stub -- robotframework is not installed."""
        def __init__(self):
            raise ImportError(
                "robotframework is not installed. "
                "Install it with: pip install robotframework robotframework-browser"
            )
