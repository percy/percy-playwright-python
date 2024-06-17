from percy.version import __version__
from percy.screenshot import percy_automate_screenshot

# import snapshot command
try:
    from percy.screenshot import percy_snapshot
except ImportError:

    def percy_snapshot(page, *a, **kw):
        raise ModuleNotFoundError(
            "[percy] `percy-playwright-python` package is not installed, "
            "please install it to use percy_snapshot command"
        )


# for better backwards compatibility
def percySnapshot(browser, *a, **kw):
    return percy_snapshot(page=browser, *a, **kw)


def percy_screenshot(page, *a, **kw):
    return percy_automate_screenshot(page, *a, **kw)
