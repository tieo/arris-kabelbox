"""Static DHCP lease management page object."""

from __future__ import annotations

import logging
from typing import Sequence

from ..core.exceptions import ApplyError
from ..core.retry import retry
from ..core.waits import settle
from ..models.dhcp_lease import DHCPLease
from .base import BasePage

log = logging.getLogger(__name__)


class DHCPPage(BasePage):
    """Manage static DHCP reservations on the ARRIS router."""

    PAGE_MID = "SettingsLan"
    _WAIT_FOR = "addScheduleHome"

    def navigate(self) -> None:
        """Navigate to DHCP page and wait for add button."""
        self._session.navigate(self.PAGE_MID, wait_for=self._WAIT_FOR)

    def list_leases(self) -> list[DHCPLease]:
        """Read all current static DHCP leases."""
        raw = self._session.execute(
            """
            var table = document.querySelector("table");
            if (!table) return [];
            var rows = table.querySelectorAll("tr");
            var result = [];
            for (var r = 0; r < rows.length; r++) {
                var tds = rows[r].querySelectorAll("td");
                if (tds.length >= 3) {
                    var name = tds[0].textContent.trim();
                    var mac = tds[1].textContent.trim();
                    var ip = tds[2].textContent.trim();
                    if (name && mac.indexOf(":") > 0)
                        result.push({name: name, mac: mac.toUpperCase(), ip: ip});
                }
            }
            return result;
            """
        )
        leases = []
        for r in raw:
            try:
                leases.append(DHCPLease(name=r["name"], mac=r["mac"], ip=r["ip"]))
            except (ValueError, KeyError) as exc:
                log.warning("Skipping malformed lease %r: %s", r, exc)
        return leases

    def _rename_lease(self, mac: str, new_name: str) -> bool:
        """Rename a lease by clicking its edit button, changing the name, and saving.

        Args:
            mac: MAC address to find the row.
            new_name: The desired display name.

        Returns:
            True if found and renamed, False if not found.
        """
        mac_upper = mac.upper()
        log.info("Renaming lease %s -> %s", mac_upper, new_name)

        # Click the edit button in the row matching this MAC
        clicked = self._session.execute(
            """
            var mac = arguments[0];
            var table = document.querySelector("table");
            if (!table) return false;
            var rows = table.querySelectorAll("tr");
            for (var r = 0; r < rows.length; r++) {
                var tds = rows[r].querySelectorAll("td");
                if (tds.length >= 3 && tds[1].textContent.trim().toUpperCase() === mac) {
                    var btn = rows[r].querySelector(".button-edit");
                    if (btn) { btn.click(); return true; }
                }
            }
            return false;
            """,
            mac_upper,
        )
        if not clicked:
            log.warning("Could not find edit button for %s", mac_upper)
            return False

        settle(2)

        # The edit popup (LANpopUpAddDevice) is now open.
        # The name field is id="deviceRename" (maxLength=63).
        # Fallback: first visible text input in popup that isn't MAC/IP sized.
        renamed = self._session.execute(
            """
            var newName = arguments[0];

            // Strategy 1: known ID for the device rename field
            var el = document.getElementById("deviceRename");
            if (el && el.getBoundingClientRect().height > 0) {
                el.value = newName;
                el.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }

            // Strategy 2: scan the popup for the name field
            var popup = document.getElementById("LANpopUpAddDevice");
            if (!popup) popup = document.querySelector(".popup");
            if (!popup) return false;

            var inputs = popup.querySelectorAll("input[type='text']");
            for (var i = 0; i < inputs.length; i++) {
                var inp = inputs[i];
                if (inp.getBoundingClientRect().height > 0 &&
                    inp.maxLength !== 2 && inp.maxLength !== 3) {
                    inp.value = newName;
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                    return true;
                }
            }

            return false;
            """,
            new_name,
        )

        if not renamed:
            log.warning("Could not find name field in edit popup for %s", mac_upper)
            # Try to close the popup
            self._session.execute(
                """
                var btn = document.getElementById("cancelButton");
                if (btn && btn.getBoundingClientRect().height > 0) btn.click();
                """
            )
            return False

        # Save the edit
        self._forms.click_button("saveButton")
        settle()

        # Check if popup is still open (error)
        still_open = self._session.execute(
            """
            var btn = document.getElementById("saveButton");
            return btn && btn.getBoundingClientRect().height > 0;
            """
        )
        if still_open:
            self._session.execute(
                """
                var btn = document.getElementById("cancelButton");
                if (btn) btn.click();
                """
            )
            log.warning("Edit popup did not close after saving for %s", mac_upper)
            return False

        log.info("Renamed %s to %s", mac_upper, new_name)
        return True

    @retry(max_attempts=3, delay=5.0)
    def add_lease(self, lease: DHCPLease) -> None:
        """Add a static DHCP reservation and set its name.

        On retry, re-navigates to get a clean page state.
        """
        log.info("Adding DHCP lease: %s %s -> %s", lease.name, lease.mac, lease.ip)

        # Always start from a clean page state
        self.navigate()

        # Check if lease already exists (idempotent)
        existing = self.list_leases()
        for l in existing:
            if l.mac == lease.mac.upper():
                if l.ip == lease.ip:
                    # Right MAC and IP, but check name
                    if l.name != lease.name:
                        self._rename_lease(lease.mac, lease.name)
                    else:
                        log.info("Lease already exists: %s", lease.mac)
                    return
                # Wrong IP, need to delete and re-add
                log.info("Lease exists with wrong IP (%s), deleting first", l.ip)
                self.delete_lease_by_mac(lease.mac)
                self.navigate()

        # Open add popup
        self._forms.click_button("addScheduleHome")
        settle()

        # Select "New Device" by value (-1)
        self._forms.set_chosen_dropdown("AddDevicesSelect", "-1")
        settle()

        # Fill MAC and IP
        self._forms.fill_mac_fields(lease.mac)
        self._forms.fill_ip_fields(lease.ip)

        # Save
        self._forms.click_button("saveButton")
        settle()

        # Check if popup is still open (error)
        still_open = self._session.execute(
            """
            var btn = document.getElementById("saveButton");
            return btn && btn.getBoundingClientRect().height > 0;
            """
        )
        if still_open:
            self._session.execute(
                """
                var btn = document.getElementById("cancelButton");
                if (btn) btn.click();
                """
            )
            raise ApplyError(f"Failed to save DHCP lease {lease.mac}")

        # Now rename from "StaticDeviceN" to the desired name
        self._rename_lease(lease.mac, lease.name)

    def delete_lease_by_mac(self, mac: str) -> bool:
        """Delete a lease by matching its MAC in the table."""
        mac_upper = mac.upper()
        found = self._session.execute(
            """
            var mac = arguments[0];
            var table = document.querySelector("table");
            if (!table) return false;
            var rows = table.querySelectorAll("tr");
            for (var r = 0; r < rows.length; r++) {
                var tds = rows[r].querySelectorAll("td");
                if (tds.length >= 3 && tds[1].textContent.trim().toUpperCase() === mac) {
                    var btn = rows[r].querySelector(".button-delete");
                    if (btn) { btn.click(); return true; }
                }
            }
            return false;
            """,
            mac_upper,
        )
        if found:
            settle()
            log.info("Deleted DHCP lease: %s", mac)
        return found

    def delete_all(self) -> int:
        """Delete all static DHCP leases."""
        count = self._tables.delete_all_rows()
        if count > 0:
            log.info("Deleted %d DHCP leases", count)
        return count

    def sync(self, desired: Sequence[DHCPLease]) -> dict:
        """Converge DHCP leases to the desired state.

        After all changes, applies once and verifies final state.
        Also renames any leases whose name doesn't match.
        """
        current = self.list_leases()
        result = {"added": 0, "deleted": 0, "unchanged": 0, "renamed": 0, "errors": []}

        desired_by_mac = {lease.mac: lease for lease in desired}
        current_by_mac = {lease.mac: lease for lease in current}

        # Delete leases not in desired
        to_delete = set(current_by_mac) - set(desired_by_mac)
        for mac in to_delete:
            try:
                self.delete_lease_by_mac(mac)
                result["deleted"] += 1
            except Exception as exc:
                log.error("Failed to delete lease %s: %s", mac, exc)
                result["errors"].append(f"delete {mac}: {exc}")

        # Add leases not in current (or with wrong IP)
        for mac, lease in desired_by_mac.items():
            existing = current_by_mac.get(mac)
            if existing and existing.ip == lease.ip:
                # Right MAC and IP, check name
                if existing.name != lease.name:
                    try:
                        self._rename_lease(mac, lease.name)
                        result["renamed"] += 1
                    except Exception as exc:
                        log.error("Failed to rename %s: %s", mac, exc)
                        result["errors"].append(f"rename {mac}: {exc}")
                else:
                    result["unchanged"] += 1
                continue
            if existing:
                try:
                    self.delete_lease_by_mac(mac)
                    result["deleted"] += 1
                except Exception as exc:
                    log.error("Failed to delete stale lease %s: %s", mac, exc)
                    result["errors"].append(f"delete stale {mac}: {exc}")
                    continue

            try:
                self.add_lease(lease)
                result["added"] += 1
            except Exception as exc:
                log.error("Failed to add lease %s: %s", lease.mac, exc)
                result["errors"].append(f"add {lease.mac}: {exc}")

        # Apply all changes at once
        if result["added"] > 0 or result["deleted"] > 0 or result["renamed"] > 0:
            self.apply()

        # Verify final state
        self.navigate()
        final = self.list_leases()
        final_by_mac = {l.mac: l for l in final}
        for mac, lease in desired_by_mac.items():
            actual = final_by_mac.get(mac)
            if not actual:
                msg = f"MISSING after sync: {lease.name} {mac}"
                log.error(msg)
                result["errors"].append(msg)
            elif actual.ip != lease.ip:
                msg = f"WRONG IP after sync: {mac} expected {lease.ip} got {actual.ip}"
                log.error(msg)
                result["errors"].append(msg)
            elif actual.name != lease.name:
                msg = f"WRONG NAME after sync: {mac} expected {lease.name!r} got {actual.name!r}"
                log.warning(msg)

        log.info(
            "DHCP sync: +%d -%d ~%d =%d",
            result["added"], result["deleted"], result["renamed"], result["unchanged"],
        )

        return result
