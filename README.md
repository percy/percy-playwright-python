# Percy playwright python
![Test](https://github.com/percy/percy-playwright-python/workflows/Test/badge.svg)

[Percy](https://percy.io) visual testing for Python Playwright.

## Installation

npm install `@percy/cli`:

```sh-session
$ npm install --save-dev @percy/cli
```

pip install Percy playwright package:

```ssh-session
$ pip install percy-playwright
```

## Usage

This is an example test using the `percy_snapshot` function.

``` python
from percy import percy_snapshot

with sync_playwright() as playwright:
  browser = playwright.chromium.connect()
  page = browser.new_page()
  page.goto('http://example.com')
  ​
  # take a snapshot
  percy_snapshot(browser, 'Python example')
```

Running the test above normally will result in the following log:

```sh-session
[percy] Percy is not running, disabling snapshots
```

When running with [`percy
exec`](https://github.com/percy/cli/tree/master/packages/cli-exec#percy-exec), and your project's
`PERCY_TOKEN`, a new Percy build will be created and snapshots will be uploaded to your project.

```sh-session
$ export PERCY_TOKEN=[your-project-token]
$ percy exec -- [python test command]
[percy] Percy has started!
[percy] Created build #1: https://percy.io/[your-project]
[percy] Snapshot taken "Python example"
[percy] Stopping percy...
[percy] Finalized build #1: https://percy.io/[your-project]
[percy] Done!
```

## Configuration

`percy_snapshot(page, name[, **kwargs])`

- `page` (**required**) - A playwright page instance
- `name` (**required**) - The snapshot name; must be unique to each snapshot
- `**kwargs` - [See per-snapshot configuration options](https://docs.percy.io/docs/cli-configuration#per-snapshot-configuration)


## Percy on Automate

## Usage

``` python
from playwright.sync_api import sync_playwright
from percy import percy_screenshot, percy_snapshot

desired_cap = {
  'browser': 'chrome',
  'browser_version': 'latest',
  'os': 'osx',
  'os_version': 'ventura',
  'name': 'Percy Playwright PoA Demo',
  'build': 'percy-playwright-python-tutorial',
  'browserstack.username': 'username',
  'browserstack.accessKey': 'accesskey'
}

with sync_playwright() as playwright:
  cdpUrl = 'wss://cdp.browserstack.com/playwright?caps=' + urllib.parse.quote(json.dumps(desired_cap))
  browser = playwright.chromium.connect(cdpUrl)
  page = browser.new_page()
  page.goto("https://percy.io/")
  percy_screenshot(page, name = "Screenshot 1")
```
# take a snapshot
percy_screenshot(page, name = 'Screenshot 1')
```

- `page` (**required**) - A Playwright page instance
- `name` (**required**) - The screenshot name; must be unique to each screenshot
- `options` (**optional**) - There are various options supported by percy_screenshot to server further functionality.
    - `sync` - Boolean value by default it falls back to `false`, Gives the processed result around screenshot [From CLI v1.28.9-beta.0+]
    - `full_page` - Boolean value by default it falls back to `false`, Takes full page screenshot [From CLI v1.28.9-beta.0+]
    - `freeze_animated_image` - Boolean value by default it falls back to `false`, you can pass `true` and percy will freeze image based animations.
    - `freeze_image_by_selectors` -List of selectors. Images will be freezed which are passed using selectors. For this to work `freeze_animated_image` must be set to true.
    - `freeze_image_by_xpaths` - List of xpaths. Images will be freezed which are passed using xpaths. For this to work `freeze_animated_image` must be set to true.
    - `percy_css` - Custom CSS to be added to DOM before the screenshot being taken. Note: This gets removed once the screenshot is taken.
    - `ignore_region_xpaths` - List of xpaths. elements in the DOM can be ignored using xpath
    - `ignore_region_selectors` - List of selectors. elements in the DOM can be ignored using selectors.
    - `custom_ignore_regions` -  List of custom objects. elements can be ignored using custom boundaries. Just passing a simple object for it like below.
      - example: ```{"top": 10, "right": 10, "bottom": 120, "left": 10}```
      - In above example it will draw rectangle of ignore region as per given coordinates.
          - `top` (int): Top coordinate of the ignore region.
          - `bottom` (int): Bottom coordinate of the ignore region.
          - `left` (int): Left coordinate of the ignore region.
          - `right` (int): Right coordinate of the ignore region.
    - `consider_region_xpaths` - List of xpaths. elements in the DOM can be considered for diffing and will be ignored by Intelli Ignore using xpaths.
    - `consider_region_selectors` - List of selectors. elements in the DOM can be considered for diffing and will be ignored by Intelli Ignore using selectors.
    - `custom_consider_regions` - List of custom objects. elements can be considered for diffing and will be ignored by Intelli Ignore using custom boundaries
      - example:```{"top": 10, "right": 10, "bottom": 120, "left": 10}```
      - In above example it will draw rectangle of consider region will be drawn.
      - Parameters:
        - `top` (int): Top coordinate of the consider region.
        - `bottom` (int): Bottom coordinate of the consider region.
        - `left` (int): Left coordinate of the consider region.
        - `right` (int): Right coordinate of the consider region.


### Creating Percy on automate build
Note: Automate Percy Token starts with `auto` keyword. The command can be triggered using `exec` keyword.

```sh-session
$ export PERCY_TOKEN=[your-project-token]
$ percy exec -- [python test command]
[percy] Percy has started!
[percy] [Python example] : Starting automate screenshot ...
[percy] Screenshot taken "Python example"
[percy] Stopping percy...
[percy] Finalized build #1: https://percy.io/[your-project]
[percy] Done!
```

Refer to docs here: [Percy on Automate](https://docs.percy.io/docs/integrate-functional-testing-with-visual-testing)
