"""Selenium wait conditions for the ARRIS router."""

from __future__ import annotations

import logging

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0


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


def settle(seconds: float = 0) -> None:
    """No-op. Kept for API compatibility."""


def wait_ready(driver: WebDriver, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Wait for the page content to load."""
    log.debug("Waiting for content to load (timeout=%.1fs)", timeout)
    try:
        WebDriverWait(driver, timeout).until(ContentLoaded())
        log.debug("Content loaded")
    except Exception:
        log.debug("Content load timed out")


def wait_for_element(
    driver: WebDriver, element_id: str, timeout: float = DEFAULT_TIMEOUT
) -> bool:
    """Wait until a specific element exists in the DOM."""
    log.debug("Waiting for element #%s (timeout=%.1fs)", element_id, timeout)
    try:
        WebDriverWait(driver, timeout).until(ElementExists(element_id))
        log.debug("Element #%s found", element_id)
        return True
    except Exception:
        log.debug("Element #%s not found", element_id)
        return False
