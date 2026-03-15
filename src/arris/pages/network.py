"""Network settings page objects (general, DynDNS)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.waits import settle
from .base import BasePage

log = logging.getLogger(__name__)


@dataclass
class DynDNSConfig:
    """DynDNS configuration snapshot."""
    enabled: bool
    provider: str
    hostname: str
    username: str
    raw_fields: dict


class NetworkGeneralPage(BasePage):
    """Network general settings (Expert mode)."""

    PAGE_MID = "NetGeneral"

    def get_raw_config(self) -> dict:
        """Read all network general settings."""
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


class DynDNSPage(BasePage):
    """DynDNS (Dynamic DNS) configuration.

    The DynDNS page fields may be hidden behind an enable toggle.
    Field IDs: ddnsApply, ddnsCancel (discovered via exploration).
    """

    PAGE_MID = "NetDDNS"

    def get_config(self) -> DynDNSConfig:
        """Read current DynDNS configuration."""
        raw = self._session.execute(
            """
            var result = {enabled: false, fields: {}};
            var content = document.getElementById("content");
            if (!content) return result;

            // Find all form fields (some may be hidden behind enable toggle)
            var inputs = content.querySelectorAll("input, select");
            for (var i = 0; i < inputs.length; i++) {
                var el = inputs[i];
                if (!el.id) continue;
                if (el.type === 'checkbox' || el.type === 'radio') {
                    result.fields[el.id] = el.checked;
                    // If it's a checkbox that looks like an enable toggle
                    if (el.id.toLowerCase().indexOf('enable') >= 0 ||
                        el.id.toLowerCase().indexOf('ddns') >= 0) {
                        if (el.type === 'checkbox') result.enabled = el.checked;
                    }
                } else if (el.tagName === 'SELECT') {
                    result.fields[el.id] = {
                        value: el.value,
                        options: Array.from(el.options).map(function(o) {
                            return {value: o.value, text: o.text, selected: o.selected};
                        })
                    };
                } else {
                    result.fields[el.id] = el.value;
                }
            }

            return result;
            """
        )
        fields = raw.get("fields", {})

        # Try to extract known field values
        provider = ""
        hostname = ""
        username = ""
        for key, val in fields.items():
            k = key.lower()
            if "provider" in k or "service" in k:
                provider = val.get("value", val) if isinstance(val, dict) else str(val)
            elif "host" in k or "domain" in k:
                hostname = str(val) if not isinstance(val, dict) else val.get("value", "")
            elif "user" in k or "login" in k:
                username = str(val) if not isinstance(val, dict) else val.get("value", "")

        return DynDNSConfig(
            enabled=raw.get("enabled", False),
            provider=provider,
            hostname=hostname,
            username=username,
            raw_fields=fields,
        )
