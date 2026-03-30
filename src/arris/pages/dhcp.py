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

    def _add_lease_in_place(self, lease: DHCPLease, max_attempts: int = 3) -> None:
        """Add a lease without navigating — assumes the page is already at SettingsLan.

        Retries by closing and reopening the popup without reloading the page.
        Use this inside sync() to avoid losing staged deletes on navigation.
        """
        for attempt in range(1, max_attempts + 1):
            # Ensure the add button is visible before clicking (page may still be loading)
            from selenium.webdriver.support.ui import WebDriverWait
            try:
                from ..core.waits import ElementVisible
                WebDriverWait(self._session.driver, 15).until(ElementVisible("addScheduleHome"))
            except Exception:
                log.warning("addScheduleHome button not visible (attempt %d)", attempt)

            # Open add popup
            self._forms.click_button("addScheduleHome")
            settle()

            # Select "New Device"
            self._forms.set_chosen_dropdown("AddDevicesSelect", "New Device")
            settle()

            # Fill MAC and IP
            self._forms.fill_mac_fields(lease.mac)
            self._forms.fill_ip_fields(lease.ip)

            # Save
            self._forms.click_button("saveButton")
            settle()

            # Check if popup closed (success)
            still_open = self._session.execute(
                """
                var btn = document.getElementById("saveButton");
                return btn && btn.getBoundingClientRect().height > 0;
                """
            )
            if not still_open:
                # Success — rename from auto-generated name to desired name
                self._rename_lease(lease.mac, lease.name)
                log.info("Added lease in-place: %s %s -> %s", lease.name, lease.mac, lease.ip)
                return

            # Close popup and retry
            self._session.execute(
                """
                var btn = document.getElementById("cancelButton");
                if (btn) btn.click();
                """
            )
            settle()
            if attempt < max_attempts:
                log.warning(
                    "_add_lease_in_place attempt %d/%d failed for %s, retrying in 2s",
                    attempt, max_attempts, lease.mac,
                )
                settle(2.0)

        raise ApplyError(f"Failed to add DHCP lease {lease.mac} after {max_attempts} attempts")

    @retry(max_attempts=3, delay=5.0)
    def add_lease(self, lease: DHCPLease) -> None:
        """Add a static DHCP reservation (standalone — navigates for clean state).

        Idempotent: if the lease already exists with the correct IP, renames if needed.
        If the lease exists with a wrong IP, deletes+applies first then re-adds.
        On retry, re-navigates to get a clean page state.
        """
        log.info("Adding DHCP lease: %s %s -> %s", lease.name, lease.mac, lease.ip)

        # Always start from a clean page state
        self.navigate()

        # Check if lease already exists (idempotent)
        existing = self.list_leases()
        for l in existing:
            if l.mac == lease.mac:
                if l.ip == lease.ip:
                    # Right MAC and IP — check name
                    if l.name != lease.name:
                        self._rename_lease(lease.mac, lease.name)
                    else:
                        log.info("Lease already exists: %s", lease.mac)
                    return
                # Wrong IP: delete, apply to persist, then re-add
                log.info("Lease exists with wrong IP (%s), deleting and applying", l.ip)
                self.delete_lease_by_mac(lease.mac)
                self.apply()
                # Fall through to add below

        self._add_lease_in_place(lease)

    def _navigate_with_recovery(self, max_attempts: int = 5) -> bool:
        """Navigate to SettingsLan, retrying and re-logging-in if the router
        session is dropped (which happens after a DHCP apply).

        Returns True if the page became ready, False if all attempts failed.
        """
        for attempt in range(1, max_attempts + 1):
            self.navigate()
            settle(1.0)
            page_ready = self._session.execute(
                """
                var btn = document.getElementById("addScheduleHome");
                return btn && btn.getBoundingClientRect().height > 0;
                """
            )
            if page_ready:
                return True
            log.warning("SettingsLan not ready (attempt %d/%d)", attempt, max_attempts)
            # Re-login if the session was dropped by the router
            try:
                logged_in = self._session.execute(
                    "return typeof isLoggedIn === 'function' && isLoggedIn();"
                )
            except Exception:
                logged_in = False
            if not logged_in:
                log.info("Session lost — re-logging in")
                try:
                    self._session.login()
                except Exception as exc:
                    log.warning("Re-login failed: %s", exc)
            settle(3.0)
        return False

    def delete_lease_by_mac(self, mac: str) -> bool:
        """Delete a lease by matching its MAC in the table.

        Note: this stages the delete in the DOM — call apply() to persist.
        """
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
            log.info("Staged delete for DHCP lease: %s", mac)
        return found

    def delete_all(self) -> int:
        """Delete all static DHCP leases."""
        count = self._tables.delete_all_rows()
        if count > 0:
            log.info("Deleted %d DHCP leases", count)
        return count

    def sync(self, desired: Sequence[DHCPLease]) -> dict:
        """Converge DHCP leases to the desired state.

        Uses a two-phase approach to avoid IP conflicts:
        - Phase 1: Delete all stale/conflicting entries, then apply.
        - Phase 2: Navigate fresh, add all missing entries without page reloads
                   between them (to avoid losing staged changes), then apply.
        - Verify final state.

        Renames any leases whose name doesn't match.
        """
        self.navigate()
        current = self.list_leases()
        result = {"added": 0, "deleted": 0, "unchanged": 0, "renamed": 0, "errors": []}

        # Use normalized MACs (DHCPLease.__post_init__ already uppercases)
        desired_by_mac = {lease.mac: lease for lease in desired}
        current_by_mac = {lease.mac: lease for lease in current}

        # Determine which IPs are being freshly claimed (will change hands)
        ips_being_claimed: set[str] = set()
        for mac, lease in desired_by_mac.items():
            cur = current_by_mac.get(mac)
            if cur is None or cur.ip != lease.ip:
                ips_being_claimed.add(lease.ip)

        # --- Phase 1: collect and delete stale/conflicting entries ---
        # Delete if:
        #   - not in desired at all
        #   - in desired but at different IP (will be re-added at correct IP)
        #   - occupying an IP that another desired entry claims (different MAC)
        macs_to_delete: set[str] = set()
        for mac, cur in current_by_mac.items():
            des = desired_by_mac.get(mac)
            if des is None:
                macs_to_delete.add(mac)
            elif des.ip != cur.ip:
                macs_to_delete.add(mac)
        # Also clear any entry (different MAC) squatting on an IP we're claiming
        for mac, cur in current_by_mac.items():
            if mac not in macs_to_delete and cur.ip in ips_being_claimed:
                macs_to_delete.add(mac)

        for mac in macs_to_delete:
            try:
                found = self.delete_lease_by_mac(mac)
                if found:
                    result["deleted"] += 1
                else:
                    log.warning("Could not stage delete for %s (not found in table)", mac)
            except Exception as exc:
                log.error("Failed to delete lease %s: %s", mac, exc)
                result["errors"].append(f"delete {mac}: {exc}")

        if result["deleted"] > 0:
            self.apply()
            # Router often resets its web session after a DHCP apply — wait for it
            settle(8.0)

        # --- Phase 2: add missing entries (no navigation between adds) ---
        self._navigate_with_recovery()
        current2 = self.list_leases()
        current2_by_mac = {lease.mac: lease for lease in current2}

        needs_apply = False
        for mac, lease in desired_by_mac.items():
            existing = current2_by_mac.get(mac)
            if existing and existing.ip == lease.ip:
                if existing.name != lease.name:
                    try:
                        self._rename_lease(mac, lease.name)
                        result["renamed"] += 1
                        needs_apply = True
                    except Exception as exc:
                        log.error("Failed to rename %s: %s", mac, exc)
                        result["errors"].append(f"rename {mac}: {exc}")
                else:
                    result["unchanged"] += 1
                continue

            # Need to add (or re-add at new IP)
            try:
                self._add_lease_in_place(lease)
                result["added"] += 1
                needs_apply = True
            except Exception as exc:
                log.error("Failed to add lease %s: %s", lease.mac, exc)
                result["errors"].append(f"add {lease.mac}: {exc}")

        if needs_apply:
            self.apply()
            settle(8.0)

        # --- Verify final state ---
        self._navigate_with_recovery()
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
                log.warning(
                    "WRONG NAME after sync: %s expected %r got %r",
                    mac, lease.name, actual.name,
                )

        log.info(
            "DHCP sync: +%d -%d ~%d =%d",
            result["added"], result["deleted"], result["renamed"], result["unchanged"],
        )

        return result
