"""Port forwarding page object."""

from __future__ import annotations

import logging
from typing import Sequence

from ..core.exceptions import ApplyError, PopupError
from ..core.retry import retry
from ..core.waits import settle, wait_ready
from ..models.port_rule import PortRule
from .base import BasePage

log = logging.getLogger(__name__)

# Router form IDs (language-independent)
_POPUP_SAVE = "PAGE_PORT_MAPPING_POPUP_ADD_SAVE"
_POPUP_CANCEL = "PAGE_PORT_MAPPING_CANCEL"
_ADD_BUTTON = "port-mapping-add"


class PortForwardingPage(BasePage):
    """Manage port forwarding rules on the ARRIS router."""

    PAGE_MID = "NetPortMapping"
    _WAIT_FOR = "port-mapping-add"

    def navigate(self) -> None:
        """Navigate to port forwarding page and wait for add button."""
        self._session.navigate(self.PAGE_MID, wait_for=self._WAIT_FOR)

    def list_rules(self) -> list[PortRule]:
        """Read all current port forwarding rules."""
        raw = self._session.execute(
            """
            var rows = document.querySelectorAll("tr[id^='mRow']");
            var result = [];
            for (var i = 0; i < rows.length; i++) {
                var tds = rows[i].querySelectorAll("td");
                if (tds.length >= 5) {
                    var toggle = rows[i].querySelector("[id^='mRowOnOff']");
                    var enabled = toggle
                        ? toggle.getAttribute('aria-checked') === 'true'
                        : false;
                    result.push({
                        name: tds[0].textContent.trim(),
                        ip: tds[1].textContent.trim(),
                        proto: tds[2].textContent.trim(),
                        lanPort: tds[3].textContent.trim(),
                        wanPort: tds[4].textContent.trim(),
                        enabled: enabled
                    });
                }
            }
            return result;
            """
        )
        rules = []
        for r in raw:
            try:
                proto = r["proto"]
                if proto not in ("TCP", "UDP", "TCP/UDP"):
                    continue
                wan_parts = r["wanPort"].split("-")
                lan_parts = r["lanPort"].split("-")
                rules.append(
                    PortRule(
                        name=r["name"],
                        protocol=proto,
                        wan_port=int(wan_parts[0]),
                        wan_port_end=int(wan_parts[-1]) if len(wan_parts) > 1 else None,
                        lan_port=int(lan_parts[0]),
                        lan_port_end=int(lan_parts[-1]) if len(lan_parts) > 1 else None,
                        lan_ip=r["ip"],
                        enabled=r.get("enabled", False),
                    )
                )
            except (ValueError, KeyError) as exc:
                log.warning("Skipping malformed rule %r: %s", r, exc)
        return rules

    def _set_rule_enabled(self, row_index: int, enabled: bool) -> bool:
        """Toggle the enable switch on a rule row.

        The toggle is a <div id="mRowOnOff{N}"> with class "button-on" or "button-off"
        and aria-checked="true"/"false".
        """
        toggle_id = f"mRowOnOff{row_index}"
        changed = self._session.execute(
            """
            var toggle = document.getElementById(arguments[0]);
            if (!toggle) return false;
            var isOn = toggle.getAttribute('aria-checked') === 'true';
            if (isOn === arguments[1]) return false;  // already in desired state
            toggle.click();
            return true;
            """,
            toggle_id,
            enabled,
        )
        if changed:
            settle()
            log.info("Toggled rule row %d -> %s", row_index, "enabled" if enabled else "disabled")
        return changed

    def enable_rule_by_match(self, protocol: str, wan_port: int, lan_ip: str, enabled: bool = True) -> bool:
        """Enable or disable a rule by matching protocol/wan_port/lan_ip.

        Returns True if the toggle was changed.
        """
        rows = self._session.execute(
            """
            var rows = document.querySelectorAll("tr[id^='mRow']");
            var result = [];
            for (var i = 0; i < rows.length; i++) {
                var tds = rows[i].querySelectorAll("td");
                if (tds.length >= 5) {
                    var toggle = rows[i].querySelector("[id^='mRowOnOff']");
                    result.push({
                        index: i,
                        proto: tds[2].textContent.trim(),
                        wanPort: tds[4].textContent.trim().split("-")[0],
                        ip: tds[1].textContent.trim(),
                        toggleId: toggle ? toggle.id : null,
                        isOn: toggle ? toggle.getAttribute('aria-checked') === 'true' : false
                    });
                }
            }
            return result;
            """
        )
        for row in rows:
            if (row["proto"] == protocol
                    and row["wanPort"] == str(wan_port)
                    and row["ip"] == lan_ip):
                if row["isOn"] == enabled:
                    return False  # already correct
                return self._set_rule_enabled(row["index"], enabled)
        log.warning("No rule found for %s:%d -> %s", protocol, wan_port, lan_ip)
        return False

    @retry(max_attempts=3, delay=5.0)
    def add_rule(self, rule: PortRule) -> None:
        """Add a single port forwarding rule, save, apply, and verify.

        IMPORTANT: The router can only reliably save one rule per apply cycle.
        On retry, re-navigates to get a clean page state.
        """
        log.info(
            "Adding port rule: %s %s %d -> %s:%d",
            rule.name, rule.protocol, rule.wan_port, rule.lan_ip, rule.lan_port,
        )

        # Always start from a clean page state
        self.navigate()

        # Check if rule already exists (idempotent)
        existing = self.list_rules()
        for r in existing:
            if r.protocol == rule.protocol and r.wan_port == rule.wan_port and r.lan_ip == rule.lan_ip:
                log.info("Rule already exists: %s", rule.name)
                return

        # Open add popup
        self._forms.click_button(_ADD_BUTTON)
        self._forms.wait_popup_open(_POPUP_SAVE)

        # Fill form
        ip_parts = rule.lan_ip.split(".")
        self._forms.set_input("servName", rule.name)
        self._forms.set_chosen_dropdown("device", "-1")
        settle()

        self._session.execute(
            """
            document.getElementById("ip0").value = arguments[0];
            document.getElementById("ip1").value = arguments[1];
            document.getElementById("ip2").value = arguments[2];
            document.getElementById("ip3").value = arguments[3];
            """,
            *ip_parts,
        )

        self._forms.set_chosen_dropdown("protocol", rule.protocol_value)
        self._forms.click_radio("pSingle")
        settle()
        self._forms.fill_port_fields(
            rule.wan_port, rule.effective_wan_end,
            rule.lan_port, rule.effective_lan_end,
        )

        # Save popup
        self._forms.click_button(_POPUP_SAVE)
        try:
            self._forms.wait_popup_close(_POPUP_SAVE)
        except PopupError:
            self._forms.click_button(_POPUP_CANCEL)
            raise ApplyError(f"Failed to save rule {rule.name}")

        # Apply immediately (one rule per apply cycle!)
        self.apply()

        # Verify: reload page and check the rule is actually there
        self.navigate()
        after = self.list_rules()
        found = any(
            r.protocol == rule.protocol and r.wan_port == rule.wan_port and r.lan_ip == rule.lan_ip
            for r in after
        )
        if not found:
            raise ApplyError(
                f"Rule {rule.name} not found after apply (router silently dropped it)"
            )

        # Enable the rule (newly added rules are disabled by default)
        if rule.enabled:
            self.enable_rule_by_match(rule.protocol, rule.wan_port, rule.lan_ip, True)
            self.apply()

        log.info("Verified: rule %s is saved and %s", rule.name, "enabled" if rule.enabled else "disabled")

    def delete_rule(self, name: str) -> bool:
        """Delete a rule by name. Returns True if found."""
        found = self._tables.click_row_button(
            row_match={name: name},
            button_class="button-delete",
            row_selector="tr[id^='mRow']",
        )
        if found:
            settle()
            self.apply()
            log.info("Deleted port rule: %s", name)
        return found

    def delete_all(self) -> int:
        """Delete all port forwarding rules."""
        count = self._tables.delete_all_rows(row_selector="tr[id^='mRow']")
        if count > 0:
            self.apply()
            log.info("Deleted %d port rules", count)
        return count

    def sync(self, desired: Sequence[PortRule]) -> dict:
        """Converge port forwarding rules to the desired state.

        After all changes, reloads and verifies final state.
        """
        current = self.list_rules()
        result = {"added": 0, "deleted": 0, "unchanged": 0, "toggled": 0, "errors": []}

        desired_set = {
            (r.protocol, r.wan_port, r.lan_ip): r for r in desired
        }
        current_set = {
            (r.protocol, r.wan_port, r.lan_ip): r for r in current
        }

        # Delete rules not in desired
        for key, rule in current_set.items():
            if key not in desired_set:
                log.info("Deleting extra rule: %s", rule.name)
                try:
                    self.delete_rule(rule.name)
                    self.navigate()
                    result["deleted"] += 1
                except Exception as exc:
                    log.error("Failed to delete %s: %s", rule.name, exc)
                    result["errors"].append(f"delete {rule.name}: {exc}")

        # Add rules not in current (add_rule handles its own navigation and verification)
        for key, rule in desired_set.items():
            existing = current_set.get(key)
            if not existing:
                log.info("Adding missing rule: %s", rule.name)
                try:
                    self.add_rule(rule)
                    result["added"] += 1
                except Exception as exc:
                    log.error("Failed to add %s: %s", rule.name, exc)
                    result["errors"].append(f"add {rule.name}: {exc}")
            else:
                # Rule exists — check enabled state
                if existing.enabled != rule.enabled:
                    try:
                        changed = self.enable_rule_by_match(
                            rule.protocol, rule.wan_port, rule.lan_ip, rule.enabled
                        )
                        if changed:
                            result["toggled"] += 1
                    except Exception as exc:
                        log.error("Failed to toggle %s: %s", rule.name, exc)
                        result["errors"].append(f"toggle {rule.name}: {exc}")
                else:
                    result["unchanged"] += 1

        # Apply if any toggles were changed
        if result["toggled"] > 0:
            self.apply()

        # Final verification: reload and compare
        self.navigate()
        final = self.list_rules()
        final_set = {(r.protocol, r.wan_port, r.lan_ip): r for r in final}
        missing = set(desired_set.keys()) - set(final_set.keys())
        if missing:
            for key in missing:
                rule = desired_set[key]
                msg = f"MISSING after sync: {rule.name} {rule.protocol}:{rule.wan_port}"
                log.error(msg)
                result["errors"].append(msg)

        # Verify enabled state
        final_by_key = {(r.protocol, r.wan_port, r.lan_ip): r for r in final}
        for key, rule in desired_set.items():
            actual = final_by_key.get(key)
            if actual and actual.enabled != rule.enabled:
                msg = f"WRONG STATE after sync: {rule.name} expected {'enabled' if rule.enabled else 'disabled'}"
                log.warning(msg)

        return result
