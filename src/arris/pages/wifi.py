"""WiFi settings page objects."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.waits import settle
from .base import BasePage

log = logging.getLogger(__name__)

_CHANGE_PASSWORD_BUTTON = "input_ChangePassword_24"
_PASSWORD_POPUP_SAVE = "PAGE_GENERAL_PASSWORD_POPUP_PASSWORD_SAVE"


# The on/off switches on this page are not inputs but divs whose class carries
# the state, "button button-on" or "button button-off"; clicking one flips it.
_SWITCHES = {
    "enabled": "wifiOnOff",
    "split_ssid": "split-ssid",
    "band_steering": "bandsteeringOnOff",
    "guest_wifi": "guestwifiOnOff",
    "broadcast_24": "broadcast_enable_24",
    "broadcast_5": "broadcast_enable_5",
    "guest_isolate": "guest_isolate",
}
# With the SSID not split, ssid-input names both bands. Split, it is the
# 2.4 GHz name and ssid-input3 the 5 GHz one.
_SSID_24 = "ssid-input"
_SSID_5 = "ssid-input3"
_SSID_GUEST = "ssid-input-guest"


@dataclass
class WifiStatus:
    """Current WiFi configuration snapshot."""
    enabled: bool
    ssid: str
    split_ssid: bool
    band_steering: bool
    guest_wifi: bool
    password_set: bool
    ssid_5g: str = ""
    broadcast_24: bool = True
    broadcast_5: bool = True
    guest_ssid: str = ""
    guest_isolate: bool = False


class WifiGeneralPage(BasePage):
    """Read and manage WiFi general settings.

    Controls on the page (ids verified against the firmware):
    - switches, see _SWITCHES
    - ssid-input / ssid-input3 / ssid-input-guest: network names
    - input_ChangePassword_24 opens the passphrase popup; the 5 GHz and guest
      buttons repeat or pad that id, so they are found by their visible row
    - applyButton / cancelButton
    """

    PAGE_MID = "WifiGeneral"

    def get_status(self) -> WifiStatus:
        """Read current WiFi status from the page."""
        raw = self._session.execute(
            """
            var switches = arguments[0], out = {switches: {}, inputs: {}};
            for (var key in switches) {
                var el = document.getElementById(switches[key]);
                out.switches[key] = el ? el.classList.contains("button-on") : null;
            }
            [arguments[1], arguments[2], arguments[3]].forEach(function (id) {
                var el = document.getElementById(id);
                out.inputs[id] = el ? el.value : "";
            });
            var pw = document.getElementById("password_24g_encrypt");
            out.password_set = pw ? pw.value.length > 0 : false;
            return out;
            """,
            _SWITCHES, _SSID_24, _SSID_5, _SSID_GUEST,
        )
        sw, inputs = raw["switches"], raw["inputs"]
        split = bool(sw.get("split_ssid"))
        return WifiStatus(
            enabled=bool(sw.get("enabled")),
            ssid=inputs.get(_SSID_24, ""),
            split_ssid=split,
            band_steering=bool(sw.get("band_steering")),
            guest_wifi=bool(sw.get("guest_wifi")),
            password_set=raw.get("password_set", False),
            ssid_5g=inputs.get(_SSID_5, "") if split else inputs.get(_SSID_24, ""),
            broadcast_24=bool(sw.get("broadcast_24")),
            broadcast_5=bool(sw.get("broadcast_5")),
            guest_ssid=inputs.get(_SSID_GUEST, ""),
            guest_isolate=bool(sw.get("guest_isolate")),
        )

    def _set_switch(self, key: str, on: bool) -> None:
        """Flip a switch only when it is not already in the wanted state."""
        element_id = _SWITCHES[key]
        current = self._session.execute(
            "var el = document.getElementById(arguments[0]);"
            "return el ? el.classList.contains('button-on') : null;",
            element_id,
        )
        if current is None:
            raise RuntimeError(f"switch #{element_id} not found on the page")
        if current != on:
            log.info("Turning %s %s", key, "on" if on else "off")
            self._forms.click_button(element_id)
            settle()

    def configure(
        self,
        *,
        enabled: bool | None = None,
        split_ssid: bool | None = None,
        band_steering: bool | None = None,
        guest_wifi: bool | None = None,
        ssid: str | None = None,
        ssid_5g: str | None = None,
        broadcast: bool | None = None,
        guest_ssid: str | None = None,
        guest_isolate: bool | None = None,
        password: str | None = None,
        password_5g: str | None = None,
        guest_password: str | None = None,
    ) -> None:
        """Stage every requested change, then apply once.

        One apply restarts the radios once. Switches go first because they
        reveal the fields that depend on them: split exposes the 5 GHz name,
        guest WiFi the guest name.
        """
        for key, value in (("enabled", enabled), ("split_ssid", split_ssid),
                           ("band_steering", band_steering), ("guest_wifi", guest_wifi),
                           ("guest_isolate", guest_isolate)):
            if value is not None:
                self._set_switch(key, value)
        if broadcast is not None:
            self._set_switch("broadcast_24", broadcast)
            self._set_switch("broadcast_5", broadcast)
        if ssid is not None:
            self._forms.set_input(_SSID_24, ssid)
        if ssid_5g is not None:
            self._forms.set_input(_SSID_5, ssid_5g)
        if guest_ssid is not None:
            self._forms.set_input(_SSID_GUEST, guest_ssid)
        if password is not None:
            self._stage_password(password)
        if password_5g is not None:
            self._stage_password(password_5g, row="5")
        if guest_password is not None:
            self._stage_password(guest_password, row="guest")
        self.apply()

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

    def set_password(self, password: str) -> None:
        """Change the WiFi passphrase and apply."""
        self._stage_password(password)
        self.apply()

    def set_ssid_and_password(self, ssid: str, password: str) -> None:
        """Change SSID and passphrase together, with a single apply.

        Two separate applies would restart the radios twice and, between them,
        broadcast the new name under the old passphrase, which is the state
        that strands every client trying to join.
        """
        log.info("Setting SSID to %r and changing the passphrase", ssid)
        self._forms.set_input("ssid-input", ssid)
        self._stage_password(password)
        self.apply()

    def _stage_password(self, password: str, row: str = "24") -> None:
        """Enter a new passphrase through the change-password popup.

        The visible field (password_24g_encrypt) is read-only; the router only
        takes a new passphrase through the popup behind the change-password
        button, which asks for it twice and has its own Save before the
        page-level Apply. The field ids are misleading on this firmware:
        password_24g is the show-password checkbox, not the passphrase, and
        the 5 GHz and guest buttons share or pad their ids, so the button is
        taken as the visible one whose id names the row.
        """
        # WPA2 takes either a passphrase of 8 to 63 characters or the raw PSK
        # as exactly 64 hex digits. The raw form is derived from passphrase and
        # SSID together, so it only works under the SSID it was derived for.
        is_raw_psk = len(password) == 64 and all(c in "0123456789abcdefABCDEF" for c in password)
        if not (8 <= len(password) <= 63 or is_raw_psk):
            raise ValueError("A WPA2 key is 8 to 63 characters, or 64 hex digits")
        log.info("Changing the %s WiFi passphrase", {"24": "main", "5": "5 GHz", "guest": "guest"}[row])
        if row == "24":
            self._forms.click_button(_CHANGE_PASSWORD_BUTTON)
        else:
            clicked = self._session.execute(
                """
                var buttons = document.querySelectorAll("input[id*='input_ChangePassword_']");
                for (var i = 0; i < buttons.length; i++) {
                    var b = buttons[i];
                    if (b.id.trim() === "input_ChangePassword_" + arguments[0] &&
                        b.getBoundingClientRect().height > 0) { b.click(); return true; }
                }
                return false;
                """,
                row,
            )
            if not clicked:
                raise RuntimeError(f"no visible change-password button for {row}; is that network on?")
        self._forms.wait_popup_open(_PASSWORD_POPUP_SAVE)
        self._forms.set_input("newPassword", password)
        self._forms.set_input("confirmPassword", password)
        self._forms.click_button(_PASSWORD_POPUP_SAVE)
        self._forms.wait_popup_close(_PASSWORD_POPUP_SAVE)

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
