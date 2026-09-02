"""
Cookie popup handler for Goethe-Institut websites.
Dismisses the Usercentrics / cookie consent overlay that blocks page interaction.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Union


def dismiss_cookie_popup(driver, logger: Optional[logging.Logger] = None) -> bool:
    """
    Dismiss the Goethe cookie consent popup.
    Works with both Selenium WebDriver and PatchrightDriver.
    Returns True if popup was found and dismissed.
    """
    log = logger or logging.getLogger("cookie_handler")

    # ── Strategy 1: Click "Accept All" or "Deny" button ──
    accept_selectors = [
        "button:has-text('Accept All')",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "button:has-text('Allow All')",
        "button:has-text('Allow all')",
        "button:has-text('Deny')",
        "button:has-text('Reject')",
        "[data-testid='uc-accept-all']",
        "[data-testid='uc Accept All']",
    ]

    for sel in accept_selectors:
        try:
            if hasattr(driver, '_page'):
                # Patchright
                btn = driver._page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=2000)
                    log.info("Cookie popup dismissed via: %s", sel)
                    time.sleep(0.5)
                    return True
            else:
                # Selenium
                from selenium.webdriver.common.by import By
                css = sel.replace(":has-text(", "[contains(text(),").replace(")", ")]")
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    if el.is_displayed():
                        el.click()
                        log.info("Cookie popup dismissed via: %s", sel)
                        time.sleep(0.5)
                        return True
        except Exception:
            continue

    # ── Strategy 2: Click any visible button with consent text ──
    consent_texts = ["accept", "allow", "agree", "ok", "got it", "consent", "deny", "reject"]
    try:
        if hasattr(driver, '_page'):
            buttons = driver._page.locator("button").all()
            for btn in buttons:
                try:
                    txt = (btn.inner_text(timeout=500) or "").strip().lower()
                    if any(ct in txt for ct in consent_texts) and btn.is_visible(timeout=500):
                        btn.click(timeout=2000)
                        log.info("Cookie popup dismissed via button text: '%s'", txt)
                        time.sleep(0.5)
                        return True
                except Exception:
                    continue
        else:
            from selenium.webdriver.common.by import By
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                try:
                    txt = (btn.text or "").strip().lower()
                    if any(ct in txt for ct in consent_texts) and btn.is_displayed():
                        btn.click()
                        log.info("Cookie popup dismissed via button text: '%s'", txt)
                        time.sleep(0.5)
                        return True
                except Exception:
                    continue
    except Exception:
        pass

    # ── Strategy 3: Hide the overlay via JS ──
    hide_js = """
        // Usercentrics shadow DOM
        var uc = document.getElementById('usercentrics-root');
        if (uc && uc.shadowRoot) {
            var btns = uc.shadowRoot.querySelectorAll('button');
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].textContent || '').toLowerCase();
                if (t.indexOf('accept') >= 0 || t.indexOf('deny') >= 0) {
                    btns[i].click();
                    return 'uc-shadow-click';
                }
            }
        }
        // Generic overlay hiding
        document.querySelectorAll('[class*="consent"], [id*="consent"], [class*="cookie"], [id*="cookie"], [class*="banner"]')
            .forEach(function(el) { el.style.display = 'none'; });
        return 'hidden';
    """
    try:
        result = driver.execute_script(hide_js)
        if result:
            log.info("Cookie popup hidden via JS: %s", result)
            time.sleep(0.3)
            return True
    except Exception:
        pass

    log.debug("No cookie popup detected")
    return False
