"""Read-only status pages."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from selenium.webdriver.support.ui import WebDriverWait

from ..core.waits import ContentLoaded, wait_ready
from .base import BasePage

log = logging.getLogger(__name__)


@dataclass
class ConnectedDevice:
    name: str
    ip: str
    mac: str
    connection: str  # "WiFi 2.4GHz", "WiFi 5GHz", "LAN"
    speed: str


@dataclass
class RouterStatus:
    connection_type: str  # "DOCSIS", etc.
    wan_ip: str
    devices: list[ConnectedDevice]


# JS that waits for #content to have device data and scrapes it.
# Returns null if content not ready yet (for use with WebDriverWait).
_SCRAPE_DEVICES_JS = """
var content = document.getElementById("content");
if (!content || content.textContent.trim().length < 20) return null;

var result = [];
var sections = content.innerHTML.split(/Name:/g);
for (var i = 1; i < sections.length; i++) {
    var s = sections[i];
    var nameMatch = s.match(/^\\s*([^<]+)/);
    var ipMatch = s.match(/IPv4:\\s*([\\d.]+)/);
    var macMatch = s.match(/MAC:\\s*([\\da-fA-F:]+)/);
    var wlanMatch = s.match(/WLAN:\\s*([^<]+)/);
    var speedMatch = s.match(/(Link Rate|Geschwindigkeit):\\s*([^<]+)/);
    if (nameMatch && ipMatch && macMatch) {
        result.push({
            name: nameMatch[1].trim(),
            ip: ipMatch[1].trim(),
            mac: macMatch[1].trim().toUpperCase(),
            connection: wlanMatch ? 'WiFi ' + wlanMatch[1].trim() : 'LAN',
            speed: speedMatch ? speedMatch[2].trim() : ''
        });
    }
}
return result.length > 0 ? result : null;
"""


class StatusPage(BasePage):
    """Read router status and connected devices."""

    PAGE_MID = "StatusStatus"

    def get_connected_devices(self) -> list[ConnectedDevice]:
        """List all devices connected to the router."""
        log.debug("Scraping connected devices")
        driver = self._session.driver
        timeout = self._session._page_timeout

        raw = WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(_SCRAPE_DEVICES_JS)
        )
        log.debug("Found %d devices", len(raw))
        return [
            ConnectedDevice(
                name=d["name"],
                ip=d["ip"],
                mac=d["mac"],
                connection=d["connection"],
                speed=d["speed"],
            )
            for d in raw
        ]

    def get_overview_text(self) -> str:
        """Get raw overview page text for debugging."""
        return self._session.execute(
            """
            var c = document.getElementById("content");
            return c ? c.textContent.trim() : "";
            """
        )


class OverviewPage(BasePage):
    """The main overview/dashboard page."""

    PAGE_MID = ""  # It's the default page

    def navigate(self) -> None:
        log.debug("Navigating to overview")
        driver = self._session.driver
        timeout = self._session._page_timeout

        # Check if already on the overview page (login lands us here)
        already = driver.execute_script(
            "var el = document.getElementById('overview_lists');"
            "return el && el.textContent.trim().length > 20;"
        )
        if not already:
            driver.execute_script("go('overview');")

        # Wait for the overview device list to appear
        log.debug("Waiting for overview_lists (timeout=%.1fs)", timeout)
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                "var el = document.getElementById('overview_lists');"
                "return el && el.textContent.trim().length > 20;"
            )
        )

    def get_connected_devices(self) -> list[ConnectedDevice]:
        """Same as StatusPage but from the overview."""
        return StatusPage(self._session).get_connected_devices()
