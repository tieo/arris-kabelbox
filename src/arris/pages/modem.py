"""Operating mode page: router, or modem only (bridge mode)."""

from __future__ import annotations

import logging

from ..core.waits import settle
from .base import BasePage

log = logging.getLogger(__name__)

# The page's two radio buttons, by id.
_RADIOS = {"router": "routerMode", "bridge": "bridgeMode"}


class ModemModePage(BasePage):
    """Switch between router mode and bridge mode.

    In bridge mode the station only passes the cable connection through on
    LAN port 1: its other LAN ports, its wifi, DHCP server and firewall stop,
    and the router behind port 1 gets the public address. The station reboots
    to change mode, and in bridge mode its own pages answer only over a LAN
    cable at the modem address the page names (pass that as the host). The page only exists in the menu where the line allows a
    modem mode (a dual-stack line with a public IPv4 address).
    """

    PAGE_MID = "SettingsModem"

    def get_mode(self) -> str:
        """The selected mode, "router" or "bridge"."""
        checked = self._session.execute(
            """
            var ids = arguments[0], out = null;
            for (var mode in ids) {
                var el = document.getElementById(ids[mode]);
                if (el && el.checked) out = mode;
            }
            return out;
            """,
            _RADIOS,
        )
        if checked is None:
            raise RuntimeError("operating mode page shows neither router nor bridge mode")
        return checked

    def set_mode(self, mode: str) -> str | None:
        """Select a mode and apply it. Returns the text of the confirmation
        dialog the station shows, if any, after confirming it. The station
        reboots afterwards, so the session ends with this call."""
        if mode not in _RADIOS:
            raise ValueError(f"mode must be one of {sorted(_RADIOS)}")
        if self.get_mode() == mode:
            log.info("Already in %s mode", mode)
            return None

        log.warning("Switching the station to %s mode", mode)
        # The input itself is hidden behind the page's styled radio, so the
        # click goes to what the user sees: its label, else its container.
        self._session.execute(
            """
            var el = document.getElementById(arguments[0]);
            var target = document.querySelector("label[for='" + arguments[0] + "']") || el.parentElement;
            target.click();
            if (!el.checked) { el.click(); }
            """,
            _RADIOS[mode],
        )
        settle(1)
        if self.get_mode() != mode:
            raise RuntimeError(f"the page did not take the {mode} mode selection")
        # This page has its own apply button, not the shared applyButton.
        self._session.execute('document.getElementById("applyButton2").click();')
        settle(3)
        # The station asks for confirmation before it reboots into the new
        # mode. Confirm the visible dialog; its text goes to the caller.
        return self._session.execute(
            """
            var dialogs = document.querySelectorAll(".ui-dialog, .modal, [role='dialog'], .popup");
            for (var i = 0; i < dialogs.length; i++) {
                var d = dialogs[i];
                if (d.getBoundingClientRect().height === 0) continue;
                var text = d.innerText.replace(/\\s+/g, " ").trim();
                var btns = d.querySelectorAll("input[type='button'], button");
                for (var j = 0; j < btns.length; j++) {
                    var b = btns[j];
                    var cls = (b.className || "") + " " + (b.id || "");
                    if (b.getBoundingClientRect().height > 0 && !/cancel/i.test(cls)) {
                        b.click();
                        return text;
                    }
                }
                return text;
            }
            return null;
            """
        )
