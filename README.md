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
- `**kwargs` - [See per-snapshot configuration options](https://www.browserstack.com/docs/percy/take-percy-snapshots/overview#per-snapshot-configuration)


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
```python
percy_screenshot(page, name = 'Screenshot 1')
```

- `page` (**required**) - A Playwright page instance
- `name` (**required**) - The screenshot name; must be unique to each screenshot
- `options` (**optional**) - There are various options supported by percy_screenshot to server further functionality.
    - `sync` - Boolean value by default it falls back to `false`, Gives the processed result around screenshot [From CLI v1.28.8]
    - `full_page` - Boolean value by default it falls back to `false`, Takes full page screenshot [From CLI v1.28.8]
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
    - `regions` parameter that allows users to apply snapshot options to specific areas of the page. This parameter is an array where each object defines a custom region with configurations.
      - Parameters:
        - `elementSelector` (optional, only one of the following must be provided, if this is not provided then full page will be considered as region)
            - `boundingBox` (object): Defines the coordinates and size of the region.
              - `x` (number): X-coordinate of the region.
              - `y` (number): Y-coordinate of the region.
              - `width` (number): Width of the region.
              - `height` (number): Height of the region.
            - `elementXpath` (string): The XPath selector for the element.
            - `elementCSS` (string): The CSS selector for the element.

        - `algorithm` (mandatory)
            - Specifies the snapshot comparison algorithm.
            - Allowed values: `standard`, `layout`, `ignore`, `intelliignore`.

        - `configuration` (required for `standard` and `intelliignore` algorithms, ignored otherwise)
            - `diffSensitivity` (number): Sensitivity level for detecting differences.
            - `imageIgnoreThreshold` (number): Threshold for ignoring minor image differences.
            - `carouselsEnabled` (boolean): Whether to enable carousel detection.
            - `bannersEnabled` (boolean): Whether to enable banner detection.
            - `adsEnabled` (boolean): Whether to enable ad detection.

         - `assertion` (optional)
            - Defines assertions to apply to the region.
            - `diffIgnoreThreshold` (number): The threshold for ignoring minor differences.

### Example Usage for regions

```
obj1 = {
  "elementSelector": {
    "elementCSS": ".ad-banner" 
  },
  "algorithm": "intelliignore",
  "configuration": {
    "diffSensitivity": 2,
    "imageIgnoreThreshold": 0.2,
    "carouselsEnabled": true,
    "bannersEnabled": true,
    "adsEnabled": true
  },
  "assertion": {
    "diffIgnoreThreshold": 0.4,
  }
};

# we can use the createRegion function

from percy import percy_snapshot
from percy.screenshot import (create_region)

obj2 = create_region(
    algorithm="intellignore",
    diffSensitivity=2,
    imageIgnoreThreshold=0.2,
    carouselsEnabled=True,
    adsEnabled=True,
    diffIgnoreThreshold=0.4
)

percy_snapshot(page, name="Homepage", regions=[obj1]);
```


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

Refer to docs here: [Percy on Automate](https://www.browserstack.com/docs/percy/integrate/functional-and-visual)
