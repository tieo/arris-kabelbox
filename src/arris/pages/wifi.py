"""WiFi settings page objects."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.waits import settle
from .base import BasePage

log = logging.getLogger(__name__)


@dataclass
class WifiStatus:
    """Current WiFi configuration snapshot."""
    enabled: bool
    ssid: str
    split_ssid: bool
    band_steering: bool
    guest_wifi: bool
    password_set: bool


class WifiGeneralPage(BasePage):
    """Read and manage WiFi general settings.

    Fields discovered via exploration:
    - ssid-input: SSID name
    - password_24g_encrypt: password field
    - password_24g: show/hide checkbox
    - input_ChangePassword_24: change password button
    - applyButton / cancelButton
    """

    PAGE_MID = "WifiGeneral"

    def get_status(self) -> WifiStatus:
        """Read current WiFi status from the page."""
        raw = self._session.execute(
            """
            var result = {};
            var content = document.getElementById("content");
            if (!content) return result;

            // SSID
            var ssidInput = document.getElementById("ssid-input");
            result.ssid = ssidInput ? ssidInput.value : "";

            // WiFi enabled — look for a toggle/checkbox by common IDs
            var wifiToggle = document.getElementById("wifiEnabled") ||
                             document.getElementById("wifi_enable");
            if (wifiToggle) {
                result.enabled = wifiToggle.checked !== undefined ? wifiToggle.checked :
                                 (wifiToggle.value === "1" || wifiToggle.value === "true");
            } else {
                // Check if content mentions "WLAN aktivieren" checkbox area
                var checkboxes = content.querySelectorAll("input[type='checkbox']");
                result.enabled = true;  // default assumption if toggle not found
                for (var i = 0; i < checkboxes.length; i++) {
                    var cb = checkboxes[i];
                    var rect = cb.getBoundingClientRect();
                    if (rect.height > 0 && cb.id && cb.id.toLowerCase().indexOf("wifi") >= 0) {
                        result.enabled = cb.checked;
                        break;
                    }
                }
            }

            // Password set
            var pwInput = document.getElementById("password_24g_encrypt");
            result.password_set = pwInput ? (pwInput.value.length > 0) : false;

            // Split SSID, band steering, guest WiFi — these are often toggles
            // We detect them by scanning checkboxes with visible state
            var allCheckboxes = content.querySelectorAll("input[type='checkbox']");
            var cbStates = {};
            for (var i = 0; i < allCheckboxes.length; i++) {
                var cb = allCheckboxes[i];
                if (cb.id && cb.getBoundingClientRect().height > 0) {
                    cbStates[cb.id] = cb.checked;
                }
            }
            result.checkboxes = cbStates;

            return result;
            """
        )
        return WifiStatus(
            enabled=raw.get("enabled", True),
            ssid=raw.get("ssid", ""),
            split_ssid=raw.get("checkboxes", {}).get("splitSSID", False),
            band_steering=raw.get("checkboxes", {}).get("bandSteering", False),
            guest_wifi=raw.get("checkboxes", {}).get("guestWifi", False),
            password_set=raw.get("password_set", False),
        )

    def get_ssid(self) -> str:
        """Get the current SSID name.

        When SuperWLAN is active, the regular ssid-input may be empty/hidden.
        Falls back to scanning all visible text inputs for SSID-like values.
        """
        return self._session.execute(
            """
            // Primary: check ssid-input
            var el = document.getElementById("ssid-input");
            if (el && el.value) return el.value;
            // Fallback: find any visible text input with an SSID-like value
            var inputs = document.querySelectorAll("input[type='text']");
            for (var i = 0; i < inputs.length; i++) {
                var inp = inputs[i];
                if (inp.getBoundingClientRect().height > 0 &&
                    inp.id && inp.id.toLowerCase().indexOf("ssid") >= 0 &&
                    inp.value) {
                    return inp.value;
                }
            }
            return el ? el.value : "";
            """
        )

    def set_ssid(self, ssid: str) -> None:
        """Change the SSID and apply."""
        log.info("Setting SSID to %r", ssid)
        self._forms.set_input("ssid-input", ssid)
        self.apply()

    def get_raw_config(self) -> dict:
        """Read all form fields as raw dict for debugging."""
        return self._session.execute(
            """
            var result = {};
            var content = document.getElementById("content");
            if (!content) return result;
            var inputs = content.querySelectorAll("input, select");
            for (var i = 0; i < inputs.length; i++) {
                var el = inputs[i];
                if (el.id && el.getBoundingClientRect().height > 0) {
                    if (el.type === 'checkbox' || el.type === 'radio') {
                        result[el.id] = el.checked;
                    } else if (el.tagName === 'SELECT') {
                        result[el.id] = {value: el.value, text: el.options[el.selectedIndex] ?
                            el.options[el.selectedIndex].text : ""};
                    } else {
                        result[el.id] = el.value;
                    }
                }
            }
            return result;
            """
        )


class WifiSchedulePage(BasePage):
    """WiFi schedule/timer settings."""

    PAGE_MID = "WifiSchedule"


class WifiMacFilterPage(BasePage):
    """WiFi MAC filter settings."""

    PAGE_MID = "WifiMacFilter"

    def list_allowed_macs(self) -> list[str]:
        """Read the MAC filter whitelist."""
        raw = self._session.execute(
            """
            var table = document.querySelector("table");
            if (!table) return [];
            var rows = table.querySelectorAll("tr");
            var macs = [];
            for (var r = 0; r < rows.length; r++) {
                var tds = rows[r].querySelectorAll("td");
                for (var c = 0; c < tds.length; c++) {
                    var text = tds[c].textContent.trim();
                    if (/^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/.test(text)) {
                        macs.push(text.toUpperCase());
                    }
                }
            }
            return macs;
            """
        )
        return raw


class WifiSettingsPage(BasePage):
    """Advanced WiFi settings (Expert mode only)."""

    PAGE_MID = "WifiSettings"

    def get_raw_config(self) -> dict:
        """Read all advanced WiFi settings."""
        return self._session.execute(
            """
            var result = {};
            var content = document.getElementById("content");
            if (!content) return result;
            var inputs = content.querySelectorAll("input, select");
            for (var i = 0; i < inputs.length; i++) {
                var el = inputs[i];
                if (el.id && el.getBoundingClientRect().height > 0) {
                    if (el.type === 'checkbox' || el.type === 'radio') {
                        result[el.id] = el.checked;
                    } else if (el.tagName === 'SELECT') {
                        result[el.id] = el.value;
                    } else {
                        result[el.id] = el.value;
                    }
                }
            }
            return result;
            """
        )
