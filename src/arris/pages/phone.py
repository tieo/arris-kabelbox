"""Telephone (VoIP) page objects: call log, numbers, settings (read-only).

Selectors are derived from the real TG3442DE phone pages and use structural
classes / image names rather than localised strings, so they stay
language-independent (the same principle as the rest of the codebase).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .base import BasePage

log = logging.getLogger(__name__)


@dataclass
class CallLogEntry:
    """A single entry from the phone call history."""
    date: str
    time: str
    direction: str  # "incoming", "outgoing", "missed", or "" if unknown
    number: str
    duration: str


@dataclass
class PhoneNumber:
    """A configured phone number / SIP account on a telephone port."""
    port: int
    number: str
    status: str
    registered: bool


class PhoneCallLogPage(BasePage):
    """Phone call history / log (read-only).

    Each call is a ``div#phoneLogItem.table-row``. Direction comes from the
    icon in ``.table-col1`` (``outgoing.png`` / ``incoming.png`` /
    ``missedcall.png``); date/time/number/duration come from the fixed
    ``.table-colN`` cells.
    """

    PAGE_MID = "PhoneCallLog"

    def get_entries(self) -> list[CallLogEntry]:
        """Read the call log as structured entries (newest first)."""
        raw = self._session.execute(
            """
            function cellText(row, cls) {
                var el = row.querySelector("." + cls);
                return el ? el.textContent.trim() : "";
            }
            var result = [];
            var rows = document.querySelectorAll("#content .table-row");
            for (var r = 0; r < rows.length; r++) {
                var row = rows[r];
                if (row.className.indexOf("table-row-head") >= 0) continue;

                // Direction from the icon image (language-independent).
                var dir = "";
                var img = row.querySelector(".table-col1 img");
                var src = img ? (img.getAttribute("src") || "") : "";
                if (src.indexOf("missed") >= 0) dir = "missed";
                else if (src.indexOf("incoming") >= 0) dir = "incoming";
                else if (src.indexOf("outgoing") >= 0) dir = "outgoing";
                else if (row.className.indexOf("missed") >= 0) dir = "missed";
                else if (row.className.indexOf("received") >= 0) dir = "incoming";
                else if (row.className.indexOf("dialled") >= 0) dir = "outgoing";

                result.push({
                    date: cellText(row, "table-col2"),
                    time: cellText(row, "table-col3"),
                    direction: dir,
                    number: cellText(row, "table-col4"),
                    duration: cellText(row, "table-col6")
                });
            }
            return result;
            """
        )
        return [
            CallLogEntry(
                date=e.get("date", ""),
                time=e.get("time", ""),
                direction=e.get("direction", ""),
                number=e.get("number", ""),
                duration=e.get("duration", ""),
            )
            for e in raw
        ]

    def get_raw_text(self) -> str:
        """Raw content text, for debugging when scraping misses fields."""
        return self._session.execute(
            'var c = document.getElementById("content"); return c ? c.textContent.trim() : "";'
        )


class PhoneNumbersPage(BasePage):
    """Configured phone numbers / SIP accounts (read-only).

    One ``table.table-three-columns`` per telephone port. Each data row is
    ``index | number | status``; a registered account has the status cell
    marked with ``class="color-green"``. Empty slots are skipped.
    """

    PAGE_MID = "PhoneNumbers"

    def list_numbers(self) -> list[PhoneNumber]:
        """List configured (non-empty) phone numbers per port."""
        raw = self._session.execute(
            """
            var result = [];
            var tables = document.querySelectorAll("#content table");
            for (var t = 0; t < tables.length; t++) {
                // Port number from the table id, e.g. phoneTable1 -> 1.
                var m = (tables[t].id || "").match(/(\\d+)/);
                var port = m ? parseInt(m[1], 10) : (t + 1);

                var rows = tables[t].querySelectorAll("tbody tr");
                for (var r = 0; r < rows.length; r++) {
                    var tds = rows[r].querySelectorAll("td");
                    if (tds.length < 3) continue;
                    var number = tds[1].textContent.trim();
                    if (!number) continue;  // empty slot

                    var statusCell = tds[2];
                    result.push({
                        port: port,
                        number: number,
                        status: statusCell.textContent.trim(),
                        registered: (statusCell.className || "").indexOf("color-green") >= 0
                    });
                }
            }
            return result;
            """
        )
        return [
            PhoneNumber(
                port=int(n.get("port", 0)),
                number=n.get("number", ""),
                status=n.get("status", ""),
                registered=bool(n.get("registered", False)),
            )
            for n in raw
        ]


class PhoneSettingsPage(BasePage):
    """Phone settings page (read-only summary).

    Settings render as ``.row`` blocks with a ``.left`` label and a ``.right``
    value. Toggles are ``div.button`` elements whose ``button-on`` /
    ``button-off`` class encodes the state.
    """

    PAGE_MID = "PhoneSettings"

    def get_settings(self) -> dict:
        """Read visible phone settings as label -> value pairs."""
        return self._session.execute(
            """
            var result = {};
            var rows = document.querySelectorAll("#content .row");
            for (var i = 0; i < rows.length; i++) {
                var left = rows[i].querySelector(".left");
                var right = rows[i].querySelector(".right");
                if (!left) continue;
                var label = left.textContent.trim();
                if (!label) continue;

                var value = "";
                var toggle = right ? right.querySelector(".button") : null;
                if (toggle) {
                    var cls = toggle.className || "";
                    value = cls.indexOf("button-on") >= 0 ? "on"
                          : cls.indexOf("button-off") >= 0 ? "off"
                          : (toggle.getAttribute("aria-label") || "").trim();
                } else if (right) {
                    value = right.textContent.trim();
                }
                result[label] = value;
            }
            return result;
            """
        )
