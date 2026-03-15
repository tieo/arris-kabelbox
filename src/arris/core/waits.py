"""Custom Selenium wait conditions for the slow ARRIS router."""

from __future__ import annotations

import logging
import time

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger(__name__)

# The router is extremely slow. These floors are non-negotiable.
MIN_SETTLE = 2.0
DEFAULT_TIMEOUT = 20.0


class ElementVisible:
    """Wait until an element is visible (has nonzero bounding rect)."""

    def __init__(self, element_id: str):
        self.element_id = element_id

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            """
            var el = document.getElementById(arguments[0]);
            return el && el.getBoundingClientRect().height > 0;
            """,
            self.element_id,
        )


class ElementHidden:
    """Wait until an element is hidden or gone."""

    def __init__(self, element_id: str):
        self.element_id = element_id

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            """
            var el = document.getElementById(arguments[0]);
            return !el || el.getBoundingClientRect().height === 0;
            """,
            self.element_id,
        )


class ElementExists:
    """Wait until an element exists in the DOM (by ID)."""

    def __init__(self, element_id: str):
        self.element_id = element_id

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            "return document.getElementById(arguments[0]) !== null;",
            self.element_id,
        )


class ContentLoaded:
    """Wait until the #content area has meaningful children."""

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            """
            var c = document.getElementById('content');
            return c && c.children.length > 0 && c.textContent.trim().length > 20;
            """
        )


class NavigationPresent:
    """Wait until the main navigation bar is rendered (confirms login)."""

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            """
            return document.querySelectorAll("[id^='navigation-item-']").length > 0;
            """
        )


class TableHasRows:
    """Wait until a table has at least one data row."""

    def __init__(self, min_rows: int = 1):
        self.min_rows = min_rows

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            """
            var rows = document.querySelectorAll("table tr");
            var dataRows = 0;
            for (var i = 0; i < rows.length; i++) {
                var tds = rows[i].querySelectorAll("td");
                if (tds.length >= 2) dataRows++;
            }
            return dataRows >= arguments[0];
            """,
            self.min_rows,
        )


class LoggedIn:
    """Wait until the router reports the session is authenticated."""

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            "return typeof isLoggedIn === 'function' && isLoggedIn();"
        )


class NoSpinner:
    """Wait until any loading spinner / overlay is gone."""

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            """
            var spinners = document.querySelectorAll(
                ".loading, .spinner, [class*='loading'], [class*='spinner']"
            );
            for (var i = 0; i < spinners.length; i++) {
                if (spinners[i].getBoundingClientRect().height > 0) return false;
            }
            return true;
            """
        )


class AjaxComplete:
    """Wait until jQuery has no active AJAX requests."""

    def __call__(self, driver: WebDriver) -> bool:
        return driver.execute_script(
            """
            if (typeof jQuery === 'undefined') return true;
            return jQuery.active === 0;
            """
        )


def settle(seconds: float = MIN_SETTLE) -> None:
    """Hard sleep floor.

    The router genuinely needs this. Actions performed too quickly
    after a page transition silently fail or hit stale elements.
    """
    time.sleep(max(seconds, MIN_SETTLE))


def wait_ready(driver: WebDriver, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Wait until the page is fully interactive.

    Polls for content, spinners, and AJAX completion, then enforces
    a minimum settle floor because the router's JS is unreliable
    even after all observable indicators say "ready".
    """
    start = time.monotonic()
    try:
        WebDriverWait(driver, timeout).until(ContentLoaded())
    except Exception:
        log.debug("ContentLoaded timed out after %.1fs", timeout)
    try:
        WebDriverWait(driver, 5.0).until(NoSpinner())
    except Exception:
        pass
    try:
        WebDriverWait(driver, 5.0).until(AjaxComplete())
    except Exception:
        pass
    # Enforce minimum settle floor
    elapsed = time.monotonic() - start
    remaining = MIN_SETTLE - elapsed
    if remaining > 0:
        time.sleep(remaining)


def wait_for_element(
    driver: WebDriver, element_id: str, timeout: float = DEFAULT_TIMEOUT
) -> bool:
    """Wait until a specific element exists in the DOM.

    Returns True if found, False on timeout.
    """
    try:
        WebDriverWait(driver, timeout).until(ElementExists(element_id))
        return True
    except Exception:
        return False
