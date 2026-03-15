"""Read-only status pages."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.waits import wait_ready
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


class StatusPage(BasePage):
    """Read router status and connected devices."""

    PAGE_MID = "StatusStatus"

    def get_connected_devices(self) -> list[ConnectedDevice]:
        """List all devices connected to the router."""
        raw = self._session.execute(
            """
            var content = document.getElementById("content");
            if (!content) return [];

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
            return result;
            """
        )
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
        self._session.execute("go('overview');")
        wait_ready(self._session.driver)

    def get_connected_devices(self) -> list[ConnectedDevice]:
        """Same as StatusPage but from the overview."""
        return StatusPage(self._session).get_connected_devices()
