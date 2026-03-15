"""Device settings, restart, and event log page objects."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.waits import settle, wait_ready
from .base import BasePage

log = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    """Basic device information."""
    firmware_version: str
    model: str
    serial: str
    raw_text: str


class DevicePage(BasePage):
    """Device/password settings."""

    PAGE_MID = "SettingsPassword"

    def get_info(self) -> DeviceInfo:
        """Read device information."""
        raw = self._session.execute(
            """
            var result = {text: "", fields: {}};
            var content = document.getElementById("content");
            if (!content) return result;
            result.text = content.textContent.trim().substring(0, 2000);

            // Try to extract structured info from visible text fields
            var spans = content.querySelectorAll("span, td, div");
            for (var i = 0; i < spans.length; i++) {
                var text = spans[i].textContent.trim();
                if (text.length > 0 && text.length < 100) {
                    result.fields[i] = text;
                }
            }
            return result;
            """
        )
        text = raw.get("text", "")
        return DeviceInfo(
            firmware_version=self._extract_pattern(text, r"(?:Firmware|Version)[:\s]+(\S+)"),
            model=self._extract_pattern(text, r"(?:Modell|Model)[:\s]+(\S+)"),
            serial=self._extract_pattern(text, r"(?:Seriennummer|Serial)[:\s]+(\S+)"),
            raw_text=text,
        )

    @staticmethod
    def _extract_pattern(text: str, pattern: str) -> str:
        import re
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1) if match else ""


class RestartPage(BasePage):
    """Router restart page. USE WITH CAUTION."""

    PAGE_MID = "StatusRestart"

    def restart(self, *, confirm: bool = False) -> None:
        """Restart the router.

        Args:
            confirm: Must be True to actually restart. Safety guard.
        """
        if not confirm:
            raise RuntimeError(
                "restart() requires confirm=True to prevent accidental reboots"
            )
        log.warning("RESTARTING ROUTER")
        # Click the first visible action button (language-independent)
        self._session.execute(
            """
            var content = document.getElementById("content");
            if (!content) return false;
            var btns = content.querySelectorAll("input[type='button']");
            for (var i = 0; i < btns.length; i++) {
                if (btns[i].getBoundingClientRect().height > 0 &&
                    btns[i].className.indexOf('button-apply') >= 0) {
                    btns[i].click();
                    return true;
                }
            }
            // Fallback: click any visible non-cancel button
            for (var i = 0; i < btns.length; i++) {
                if (btns[i].getBoundingClientRect().height > 0 &&
                    btns[i].id !== 'cancelButton') {
                    btns[i].click();
                    return true;
                }
            }
            return false;
            """
        )
        settle(3)
        # Confirm any dialog that appears (language-independent: click OK/confirm button)
        self._session.execute(
            """
            var btns = document.querySelectorAll("input[type='button']");
            for (var i = 0; i < btns.length; i++) {
                if (btns[i].getBoundingClientRect().height > 0 &&
                    btns[i].className.indexOf('button-apply') >= 0) {
                    btns[i].click();
                    return true;
                }
            }
            // Fallback: click any visible non-cancel confirmation button
            for (var i = 0; i < btns.length; i++) {
                var btn = btns[i];
                if (btn.getBoundingClientRect().height > 0 &&
                    btn.id !== 'cancelButton' &&
                    btn.className.indexOf('cancel') < 0) {
                    btn.click();
                    return true;
                }
            }
            return false;
            """
        )


class AboutPage(BasePage):
    """Router about/info page (read-only)."""

    PAGE_MID = "StatusAbout"

    def get_info(self) -> dict:
        """Read firmware version and hardware info."""
        return self._session.execute(
            """
            var result = {};
            var content = document.getElementById("content");
            if (!content) return result;
            result.text = content.textContent.trim().substring(0, 2000);

            // Parse key-value pairs from the about page
            var rows = content.querySelectorAll("tr, div.row, .info-row");
            for (var i = 0; i < rows.length; i++) {
                var cells = rows[i].querySelectorAll("td, span, div");
                if (cells.length >= 2) {
                    var key = cells[0].textContent.trim();
                    var val = cells[1].textContent.trim();
                    if (key && val && key.length < 50) {
                        result[key] = val;
                    }
                }
            }
            return result;
            """
        )


class EventLogPage(BasePage):
    """Router event log (read-only)."""

    PAGE_MID = "StatusEventLog"

    def get_log(self) -> str:
        """Read the event log text."""
        return self._session.execute(
            """
            var c = document.getElementById("content");
            return c ? c.textContent.trim() : "";
            """
        )

    def get_log_entries(self) -> list[dict]:
        """Read event log as structured entries (skips header row)."""
        return self._session.execute(
            """
            var result = [];
            var table = document.querySelector("table");
            if (!table) return result;
            var rows = table.querySelectorAll("tr");
            // Skip first row (header with th or first tr)
            for (var r = 0; r < rows.length; r++) {
                // Skip header rows (those with <th> cells)
                if (rows[r].querySelector("th")) continue;
                var tds = rows[r].querySelectorAll("td");
                if (tds.length >= 2) {
                    var time = tds[0].textContent.trim();
                    // Skip if this looks like a header (no digits = not a timestamp)
                    if (!/[0-9]/.test(time)) continue;
                    result.push({
                        time: time,
                        message: tds[tds.length - 1].textContent.trim()
                    });
                }
            }
            return result;
            """
        )
