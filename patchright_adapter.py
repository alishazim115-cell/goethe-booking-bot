"""
Patchright Adapter — wraps Patchright (Playwright fork) to provide
a Selenium-compatible API so booking_helper.py works unchanged.

Key: Patchright patches CDP at the protocol layer, removing the
Runtime.enable leak and navigator.webdriver flag that Cloudflare detects.
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from patchright.sync_api import sync_playwright, Page, Browser, BrowserContext

try:
    from selenium.webdriver.common.by import By
except ImportError:
    class By:
        CSS_SELECTOR = "css"
        XPATH = "xpath"
        TAG_NAME = "tag"

try:
    from selenium.common.exceptions import (
        NoSuchElementException,
        TimeoutException,
        StaleElementReferenceException,
        WebDriverException,
    )
except ImportError:
    class NoSuchElementException(Exception): pass
    class TimeoutException(Exception): pass
    class StaleElementReferenceException(Exception): pass
    class WebDriverException(Exception): pass


# ---------------------------------------------------------------------------
# Element adapter — wraps Patchright Locator to look like Selenium WebElement
# ---------------------------------------------------------------------------

class PatchrightElement:
    """Wraps a Patchright Locator to provide Selenium WebElement API."""

    def __init__(self, page: Page, locator, selector_str: str = ""):
        self._page = page
        self._locator = locator
        self._selector = selector_str

    # ── Click ──
    def click(self):
        try:
            self._locator.click(timeout=5000)
        except Exception:
            self._page.evaluate("arguments[0].click();", self._locator.element_handle(timeout=3000))

    def safe_click(self):
        """Click via JS as fallback."""
        try:
            self._locator.click(timeout=3000)
        except Exception:
            try:
                handle = self._locator.element_handle(timeout=3000)
                if handle:
                    self._page.evaluate("arguments[0].click();", handle)
            except Exception:
                pass

    # ── Text input ──
    def send_keys(self, text: str):
        try:
            self._locator.fill(text, timeout=3000)
        except Exception:
            handle = self._locator.element_handle(timeout=3000)
            if handle:
                self._page.evaluate("arguments[0].value = arguments[1];", handle, text)

    def clear(self):
        try:
            self._locator.fill("", timeout=3000)
        except Exception:
            pass

    # ── Properties ──
    @property
    def text(self) -> str:
        try:
            return self._locator.inner_text(timeout=3000) or ""
        except Exception:
            return ""

    @property
    def tag_name(self) -> str:
        try:
            handle = self._locator.element_handle(timeout=3000)
            if handle:
                return self._page.evaluate("el => el.tagName.toLowerCase()", handle) or ""
        except Exception:
            pass
        return ""

    def get_attribute(self, name: str) -> Optional[str]:
        try:
            return self._locator.get_attribute(name, timeout=3000)
        except Exception:
            return None

    def is_displayed(self) -> bool:
        try:
            return self._locator.is_visible(timeout=2000)
        except Exception:
            return False

    def is_enabled(self) -> bool:
        try:
            return self._locator.is_enabled(timeout=2000)
        except Exception:
            return False

    def is_selected(self) -> bool:
        try:
            return self._locator.is_checked(timeout=2000)
        except Exception:
            return False

    @property
    def size(self) -> Dict[str, int]:
        try:
            box = self._locator.bounding_box(timeout=2000)
            if box:
                return {"width": int(box["width"]), "height": int(box["height"])}
        except Exception:
            pass
        return {"width": 0, "height": 0}

    @property
    def location(self) -> Dict[str, int]:
        try:
            box = self._locator.bounding_box(timeout=2000)
            if box:
                return {"x": int(box["x"]), "y": int(box["y"])}
        except Exception:
            pass
        return {"x": 0, "y": 0}

    def find_element(self, by, value: str):
        """Find child element (used by button_row_text, etc.)."""
        handle = self._locator.element_handle(timeout=3000)
        if not handle:
            raise NoSuchElementException(f"Parent element not found: {self._selector}")
        child = handle.query_selector(value)
        if not child:
            raise NoSuchElementException(f"Child not found: {value}")
        return PatchrightElement(self._page, self._page.locator(f"css={value}"), value)


# ---------------------------------------------------------------------------
# Driver adapter — wraps Patchright Page to look like Selenium WebDriver
# ---------------------------------------------------------------------------

class PatchrightDriver:
    """Wraps Patchright Page to provide Selenium-compatible WebDriver API."""

    def __init__(self, page: Page, browser: Browser, context: BrowserContext,
                 logger: Optional[logging.Logger] = None):
        self._page = page
        self._browser = browser
        self._context = context
        self._logger = logger or logging.getLogger("patchright_adapter")
        self._page.set_default_timeout(30000)

    # ── Navigation ──
    def get(self, url: str):
        try:
            self._logger.info("[PATCHRIGHT] NAVIGATING: %s (current: %s)", url, self._page.url)
            self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)
            self._logger.info("[PATCHRIGHT] NAV DONE: title='%s' url=%s", self._page.title(), self._page.url)
        except Exception as exc:
            self._logger.warning("Navigation error (retrying): %s", str(exc)[:100])
            try:
                self._page.goto(url, wait_until="commit", timeout=60000)
            except Exception:
                pass

    def refresh(self):
        try:
            self._page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            try:
                self._page.reload(wait_until="commit", timeout=30000)
            except Exception:
                pass

    # ── Properties ──
    @property
    def current_url(self) -> str:
        return self._page.url or ""

    @property
    def title(self) -> str:
        try:
            return self._page.title() or ""
        except Exception:
            return ""

    @property
    def page_source(self) -> str:
        try:
            return self._page.content() or ""
        except Exception:
            return ""

    # ── Element finding ──
    def find_element(self, by, value: str):
        """Find single element. Returns PatchrightElement."""
        selector = self._to_selector(by, value)
        locator = self._page.locator(selector)
        try:
            locator.first.wait_for(state="attached", timeout=10000)
        except Exception:
            raise NoSuchElementException(f"Element not found: {value}")
        return PatchrightElement(self._page, locator.first, selector)

    def find_elements(self, by, value: str) -> List[PatchrightElement]:
        """Find multiple elements. Returns list of PatchrightElement."""
        selector = self._to_selector(by, value)
        try:
            handles = self._page.locator(selector).all()
            return [PatchrightElement(self._page, h, selector) for h in handles]
        except Exception:
            return []

    def _to_selector(self, by, value: str) -> str:
        """Convert Selenium By to Patchright selector string."""
        by_str = str(by).lower()
        if "css" in by_str:
            return value
        elif "xpath" in by_str:
            return f"xpath={value}"
        elif "tag" in by_str:
            return value
        elif "id" in by_str:
            return f"#{value}" if not value.startswith("#") else value
        elif "name" in by_str:
            return f"[name='{value}']"
        else:
            return value

    # ── JS execution ──
    def execute_script(self, script: str, *args):
        """Execute JavaScript. Patchright handles arguments differently."""
        try:
            if args:
                # Convert PatchrightElement args to element handles
                js_args = []
                for arg in args:
                    if isinstance(arg, PatchrightElement):
                        handle = arg._locator.element_handle(timeout=5000)
                        js_args.append(handle)
                    else:
                        js_args.append(arg)
                return self._page.evaluate(script, *js_args)
            else:
                return self._page.evaluate(script)
        except Exception as exc:
            self._logger.debug("execute_script error: %s", str(exc)[:80])
            return None

    # ── Screenshots ──
    def save_screenshot(self, path: str):
        try:
            self._page.screenshot(path=path, full_page=False)
        except Exception as exc:
            self._logger.debug("Screenshot failed: %s", str(exc)[:80])

    # ── Cookies ──
    def add_cookie(self, cookie: Dict):
        try:
            self._context.add_cookies([cookie])
        except Exception:
            pass

    # ── Tab management ──
    @property
    def window_handles(self) -> List:
        if self._browser:
            return list(self._context.pages)
        return list(self._context.pages)

    def switch_to_window(self, handle):
        try:
            handle.bring_to_front()
        except Exception:
            pass

    def close_window(self):
        try:
            self._page.close()
        except Exception:
            pass

    def enforce_single_tab(self):
        """Close extra tabs, keep only the last one."""
        pages = list(self._context.pages)
        if len(pages) <= 1:
            return
        keep = pages[-1]
        for p in pages:
            if p != keep:
                try:
                    p.close()
                except Exception:
                    pass
        keep.bring_to_front()

    # ── Cleanup ──
    def quit(self):
        try:
            if self._browser:
                self._browser.close()
            else:
                self._context.close()
        except Exception:
            pass

    def __del__(self):
        try:
            if self._browser:
                self._browser.close()
            else:
                self._context.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Human-like mouse movement
# ---------------------------------------------------------------------------

def human_move_and_click_patchright(driver: PatchrightDriver, element: PatchrightElement) -> None:
    """Move mouse in Bezier curve to element, then click with human-like delay."""
    try:
        # Scroll element into view
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    except Exception:
        pass

    try:
        driver.execute_script("arguments[0].removeAttribute('target');", element)
    except Exception:
        pass

    time.sleep(random.uniform(0.3, 0.8))

    try:
        box = element._locator.bounding_box(timeout=3000)
        if box:
            target_x = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
            target_y = box["y"] + box["height"] / 2 + random.uniform(-2, 2)

            # Bezier curve from random start point
            start_x = random.uniform(100, 700)
            start_y = random.uniform(100, 400)
            cp_x = start_x + (target_x - start_x) * 0.4 + random.uniform(-40, 40)
            cp_y = start_y + (target_y - start_y) * 0.6 + random.uniform(-20, 20)

            steps = random.randint(12, 22)
            for i in range(steps + 1):
                t = i / steps
                x = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * cp_x + t ** 2 * target_x
                y = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * cp_y + t ** 2 * target_y
                driver._page.mouse.move(x, y)
                time.sleep(random.uniform(0.008, 0.025))

            time.sleep(random.uniform(0.08, 0.25))
            driver._page.mouse.click(target_x, target_y)
        else:
            element.click()
    except Exception:
        element.safe_click()


# ---------------------------------------------------------------------------
# Factory — create Patchright driver
# ---------------------------------------------------------------------------

def create_patchright_driver(
    use_headless: bool = False,
    logger: Optional[logging.Logger] = None,
    proxy: Optional[str] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[tuple] = None,
) -> PatchrightDriver:
    """Launch Patchright Chromium with persistent context and warm up Akamai cookies."""
    logger = logger or logging.getLogger("patchright_adapter")

    pw = sync_playwright().start()

    # Persistent profile for cookie persistence across sessions
    profile_dir = Path.home() / "goethe-bot-profiles" / "patchright_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    launch_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
    ]
    if proxy:
        launch_args.append(f"--proxy-server={proxy}")

    vp = viewport or (1366, 768)

    # Try channel="chrome" first (uses system Chrome), fall back to bundled Chromium
    try:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=use_headless,
            channel="chrome",
            args=launch_args,
            viewport={"width": vp[0], "height": vp[1]},
            user_agent=user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US",
        )
        logger.info("Launched with system Chrome (channel=chrome)")
    except Exception:
        logger.info("System Chrome not found, using Patchright bundled Chromium")
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=use_headless,
            args=launch_args,
            viewport={"width": vp[0], "height": vp[1]},
            user_agent=user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US",
        )

    page = context.new_page()

    # Warm up: visit homepage to get Akamai cookies before exam page
    logger.info("Warming up: visiting Goethe homepage for Akamai cookies...")
    try:
        page.goto("https://www.goethe.de", wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)
        title = page.title()
        logger.info("Warm-up complete: Akamai cookies acquired (title='%s')", title)
    except Exception as exc:
        logger.warning("Warm-up failed (proceeding anyway): %s", str(exc)[:80])

    logger.info("Patchright driver created: headless=%s, viewport=%sx%s, proxy=%s, profile=%s",
                use_headless, vp[0], vp[1], proxy or "none", str(profile_dir))

    return PatchrightDriver(page, None, context, logger)
