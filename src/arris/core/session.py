"""Browser session lifecycle and router authentication."""

from __future__ import annotations

import logging
import time
from typing import Self

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from .exceptions import LoginError, NavigationError, SessionExpiredError
from .retry import retry
from .waits import wait_ready, wait_for_element

log = logging.getLogger(__name__)

# The router's session timeout is ~5 minutes of inactivity.
SESSION_TIMEOUT = 240  # re-login proactively at 4 min

# Map of page mid values to their URL query strings.
# This is mode-independent — works in both Standard and Expert.
PAGE_ROUTES: dict[str, str] = {
    "NetPortMapping": "net_port_mapping&mid=NetPortMapping",
    "NetFirewall": "net_firewall&mid=NetFirewall",
    "NetGeneral": "net_general&mid=NetGeneral",
    "NetDDNS": "net_ddns&mid=NetDDNS",
    "WifiGeneral": "wifi_general&mid=WifiGeneral",
    "WifiSchedule": "wifi_schedule&mid=WifiSchedule",
    "WifiWps": "wifi_wps&mid=WifiWps",
    "WifiMacFilter": "wifi_mac_filter&mid=WifiMacFilter",
    "WifiSettings": "wifi_settings&mid=WifiSettings",
    "WifiRadar": "wifi_radar&mid=WifiRadar",
    "WifiBandSteer": "wifi_band_steering&mid=WifiBandSteer",
    "SettingsPassword": "settings_device&mid=SettingsPassword",
    "SettingsLan": "settings_lan&mid=SettingsLan",
    "SettingsWan": "settings_wan&mid=SettingsWan",
    "SettingsModem": "settings_modem&mid=SettingsModem",
    "StatusStatus": "status_status&mid=StatusStatus",
    "StatusDiagnosticUtility": "status_diagnostic_utility&mid=StatusDiagnosticUtility",
    "StatusRestart": "status_restart&mid=StatusRestart",
    "StatusAbout": "status_about&mid=StatusAbout",
    "StatusEventLog": "status_event_log&mid=StatusEventLog",
    "PhoneCallLog": "phone_call_log&mid=PhoneCallLog",
    "PhoneNumbers": "phone_numbers&mid=PhoneNumbers",
    "PhoneSettings": "phone_settings&mid=PhoneSettings",
}


class RouterSession:
    """Manages a browser session with the ARRIS router.

    Usage::

        with RouterSession("192.168.0.1", "mypassword") as session:
            driver = session.driver
            # ... do stuff
    """

    def __init__(
        self,
        host: str = "192.168.0.1",
        password: str = "",
        *,
        headless: bool = True,
        page_timeout: float = 30.0,
        screenshot_dir: str = "/tmp",
    ):
        self.host = host
        self._password = password
        self._headless = headless
        self._page_timeout = page_timeout
        self._screenshot_dir = screenshot_dir
        self._driver: webdriver.Firefox | None = None
        self._last_activity: float = 0

    def __enter__(self) -> Self:
        self._start_browser()
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            try:
                self.screenshot(
                    f"{self._screenshot_dir}/arris-error-{int(time.time())}.png"
                )
            except Exception:
                pass
        self.close()

    def close(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    @property
    def driver(self) -> webdriver.Firefox:
        if self._driver is None:
            raise RuntimeError("Session not started — use as context manager")
        self._check_session_freshness()
        return self._driver

    @property
    def url(self) -> str:
        return f"http://{self.host}"

    def _start_browser(self) -> None:
        log.info("Starting Firefox%s", " (headless)" if self._headless else "")
        opts = Options()
        if self._headless:
            opts.add_argument("--headless")
        opts.set_preference("dom.webdriver.enabled", False)
        self._driver = webdriver.Firefox(options=opts)
        self._driver.set_page_load_timeout(self._page_timeout)
        self._driver.implicitly_wait(2)
        log.debug("Browser started")

    @retry(max_attempts=3, delay=5.0)
    def login(self) -> None:
        """Authenticate with the router via its JS login function."""
        assert self._driver is not None
        log.info("Logging in to %s", self.url)
        login_start = time.monotonic()

        log.debug("Loading router page")
        self._driver.get(self.url)
        self._wait_for_js()

        # Check if already logged in
        if self._is_logged_in():
            log.info("Already logged in")
            self._ensure_expert_mode()
            self._touch()
            return

        # Execute the router's own login function — it handles SJCL crypto.
        log.debug("Executing login function")
        result = self._driver.execute_script(
            'return login("admin", arguments[0]);', self._password
        )
        log.debug("Login function returned: %s", result)

        # Wait for the server to actually establish the session.
        # login() returns immediately but the AJAX round-trip takes time.
        log.debug("Waiting for session to be established")
        try:
            WebDriverWait(self._driver, 10).until(
                lambda d: d.execute_script(
                    "return typeof isLoggedIn === 'function' && isLoggedIn();"
                )
            )
            log.debug("Session established")
        except Exception:
            if not result:
                raise LoginError("Login returned false — wrong password or locked out")
            raise LoginError("Login function returned true but session was not established")

        self._ensure_expert_mode()
        self._touch()
        log.info("Login successful (%.1fs)", time.monotonic() - login_start)

    def _wait_for_js(self) -> None:
        """Wait for the router's JS to initialize after a page load.

        We need the login/isLoggedIn functions to exist before we can
        call them. driver.get() waits for DOMContentLoaded but not for
        all scripts to execute.
        """
        log.debug("Waiting for JS functions")
        try:
            WebDriverWait(self._driver, self._page_timeout).until(
                lambda d: d.execute_script(
                    """
                    return (typeof login === 'function') ||
                           (typeof isLoggedIn === 'function');
                    """
                )
            )
            log.debug("JS functions available")
        except Exception:
            log.warning("JS functions not found within timeout")

    def _is_logged_in(self) -> bool:
        result = self._driver.execute_script(
            "return typeof isLoggedIn === 'function' && isLoggedIn();"
        )
        log.debug("isLoggedIn() = %s", result)
        return result

    def _ensure_expert_mode(self) -> None:
        """Switch to Expert mode if not already there."""
        current = self._driver.execute_script(
            """
            var sel = document.getElementById("userModeSelect");
            return sel ? sel.value : null;
            """
        )
        log.debug("Current mode: %s", current)
        if current == "2":
            log.debug("Already in Expert mode")
            return

        log.info("Switching to Expert mode (was %s)", current)
        self._driver.execute_script(
            """
            var sel = document.getElementById("userModeSelect");
            if (sel) {
                sel.value = "2";
                if (typeof jQuery !== 'undefined') {
                    jQuery(sel).trigger("chosen:updated").trigger("change");
                } else {
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                }
            }
            """
        )

    def navigate(self, page_mid: str, wait_for: str | None = None) -> None:
        """Navigate to a page by its mid parameter.

        Args:
            page_mid: The mid parameter value, e.g. "NetPortMapping".
            wait_for: Optional element ID to wait for after navigation.
        """
        log.info("Navigating to %s", page_mid)

        # Try clicking the matching nav link by scanning all sub-nav items
        clicked = self.driver.execute_script(
            """
            var mid = arguments[0];
            var links = document.querySelectorAll("[id^='sub-navigation-item-'] a");
            for (var i = 0; i < links.length; i++) {
                if (links[i].href && links[i].href.indexOf("mid=" + mid) >= 0) {
                    links[i].click();
                    return true;
                }
            }
            return false;
            """,
            page_mid,
        )

        if not clicked:
            route = PAGE_ROUTES.get(page_mid)
            if route:
                log.debug("Nav link not found, falling back to URL: %s", route)
                self._driver.get(f"{self.url}/?{route}")
            else:
                raise NavigationError(f"Unknown page mid: {page_mid}")

        wait_ready(self._driver, self._page_timeout)

        if wait_for:
            if not wait_for_element(self._driver, wait_for, self._page_timeout):
                log.warning("Element #%s not found after navigating to %s", wait_for, page_mid)

        self._touch()
        log.debug("Navigation to %s complete", page_mid)

    def apply(self) -> None:
        """Click the page-level Apply button and wait for the router to save."""
        log.info("Clicking Apply")
        self.driver.execute_script(
            'document.getElementById("applyButton").click();'
        )
        # Wait for any loading overlay to disappear
        log.debug("Waiting for overlay to clear")
        try:
            WebDriverWait(self._driver, 15).until(
                lambda d: d.execute_script(
                    """
                    var overlay = document.querySelector('.loading-overlay, .overlay');
                    return !overlay || overlay.getBoundingClientRect().height === 0;
                    """
                )
            )
            log.debug("Overlay cleared")
        except Exception:
            log.debug("Overlay wait timed out")
        self._touch()

    def execute(self, script: str, *args) -> object:
        """Execute JavaScript on the router page."""
        self._check_session_freshness()
        result = self._driver.execute_script(script, *args)  # type: ignore[union-attr]
        self._touch()
        return result

    def screenshot(self, path: str | None = None) -> str:
        """Save a screenshot for debugging."""
        if path is None:
            path = f"{self._screenshot_dir}/arris-debug-{int(time.time())}.png"
        if self._driver:
            self._driver.save_screenshot(path)
            log.info("Screenshot saved to %s", path)
        return path

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    def _check_session_freshness(self) -> None:
        if not self._last_activity:
            return
        elapsed = time.monotonic() - self._last_activity
        if elapsed > SESSION_TIMEOUT:
            log.warning("Session idle for %.0fs, re-authenticating", elapsed)
            self.login()

    def __repr__(self) -> str:
        return f"RouterSession(host={self.host!r}, connected={self._driver is not None})"
