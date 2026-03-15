"""Firewall settings page object."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.waits import settle
from .base import BasePage

log = logging.getLogger(__name__)


@dataclass
class FirewallStatus:
    """Current firewall configuration snapshot."""
    enabled: bool
    raw_fields: dict


class FirewallPage(BasePage):
    """Read and manage firewall settings.

    The firewall page has a simple enable/disable toggle with Apply/Cancel.
    Field IDs discovered via exploration:
    - applyButton / cancelButton (the only visible fields)
    - The enable toggle is a checkbox in the content area
    """

    PAGE_MID = "NetFirewall"

    def get_status(self) -> FirewallStatus:
        """Read current firewall status."""
        raw = self._session.execute(
            """
            var result = {enabled: true, fields: {}};
            var content = document.getElementById("content");
            if (!content) return result;

            // Find the firewall enable checkbox/toggle
            var checkboxes = content.querySelectorAll("input[type='checkbox']");
            for (var i = 0; i < checkboxes.length; i++) {
                var cb = checkboxes[i];
                if (cb.getBoundingClientRect().height > 0) {
                    result.enabled = cb.checked;
                    result.fields[cb.id || "checkbox_" + i] = cb.checked;
                    break;
                }
            }

            // Also capture any other visible form fields
            var inputs = content.querySelectorAll("input, select");
            for (var i = 0; i < inputs.length; i++) {
                var el = inputs[i];
                if (el.id && el.getBoundingClientRect().height > 0) {
                    if (el.type === 'checkbox' || el.type === 'radio') {
                        result.fields[el.id] = el.checked;
                    } else {
                        result.fields[el.id] = el.value;
                    }
                }
            }
            return result;
            """
        )
        return FirewallStatus(
            enabled=raw.get("enabled", True),
            raw_fields=raw.get("fields", {}),
        )

    def is_enabled(self) -> bool:
        """Check if the firewall is currently enabled."""
        return self.get_status().enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the firewall."""
        current = self.get_status()
        if current.enabled == enabled:
            log.info("Firewall already %s", "enabled" if enabled else "disabled")
            return

        log.info("%s firewall", "Enabling" if enabled else "Disabling")
        self._session.execute(
            """
            var content = document.getElementById("content");
            if (!content) return;
            var checkboxes = content.querySelectorAll("input[type='checkbox']");
            for (var i = 0; i < checkboxes.length; i++) {
                var cb = checkboxes[i];
                if (cb.getBoundingClientRect().height > 0) {
                    cb.checked = arguments[0];
                    cb.dispatchEvent(new Event('change', {bubbles: true}));
                    break;
                }
            }
            """,
            enabled,
        )
        settle(1)
        self.apply()
