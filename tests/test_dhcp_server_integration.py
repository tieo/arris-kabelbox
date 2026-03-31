"""Integration tests for DHCP server pool management — runs against a real Kabelbox.

Requires:
  - KABELBOX_PASSWORD env var set
  - Router reachable at 192.168.0.1 (or KABELBOX_HOST)
  - Firefox + geckodriver installed

Run with:
  KABELBOX_PASSWORD=xxx pytest tests/test_dhcp_server_integration.py -v -s

Write tests (add/remove dummy lease, pool changes) require:
  KABELBOX_PASSWORD=xxx KABELBOX_WRITE_TEST=1 pytest ... -v -s
"""

from __future__ import annotations

import os
import time

import pytest

from arris.core.session import RouterSession
from arris.pages.dhcp import DHCPPage, DHCPServerStatus


# ---------------------------------------------------------------------------
# Skip unless explicitly opted in
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not os.environ.get("KABELBOX_PASSWORD"),
    reason="Set KABELBOX_PASSWORD to run integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session():
    """Single browser session shared across all tests in this module."""
    host = os.environ.get("KABELBOX_HOST", "192.168.0.1")
    password = os.environ.get("KABELBOX_PASSWORD", "")
    with RouterSession(host, password, headless=True) as s:
        yield s


@pytest.fixture(scope="module")
def dhcp_page(session):
    """DHCPPage backed by the real session."""
    return DHCPPage(session)


# ---------------------------------------------------------------------------
# Read-only tests — safe to run anytime
# ---------------------------------------------------------------------------


class TestReadDHCPStatus:
    """Read the DHCP server status without changing anything."""

    def test_get_status_returns_dataclass(self, dhcp_page):
        status = dhcp_page.get_dhcp_server_status()
        assert isinstance(status, DHCPServerStatus)
        print(f"\nDHCP status: pool {status.pool_start} - {status.pool_end}, "
              f"gw {status.gateway}, mask {status.netmask}, "
              f"enabled={status.enabled}")

    def test_pool_start_is_valid_ip(self, dhcp_page):
        status = dhcp_page.get_dhcp_server_status()
        parts = status.pool_start.split(".")
        assert len(parts) == 4, f"Not a valid IP: {status.pool_start}"
        for p in parts:
            assert p.isdigit() and 0 <= int(p) <= 255

    def test_pool_end_is_valid_ip(self, dhcp_page):
        status = dhcp_page.get_dhcp_server_status()
        parts = status.pool_end.split(".")
        assert len(parts) == 4, f"Not a valid IP: {status.pool_end}"
        for p in parts:
            assert p.isdigit() and 0 <= int(p) <= 255

    def test_gateway_is_valid_ip(self, dhcp_page):
        status = dhcp_page.get_dhcp_server_status()
        parts = status.gateway.split(".")
        assert len(parts) == 4, f"Not a valid IP: {status.gateway}"

    def test_status_consistent_on_repeat(self, dhcp_page):
        """Two consecutive reads return the same values."""
        s1 = dhcp_page.get_dhcp_server_status()
        s2 = dhcp_page.get_dhcp_server_status()
        assert s1.pool_start == s2.pool_start
        assert s1.pool_end == s2.pool_end
        assert s1.gateway == s2.gateway

    def test_enabled_property(self, dhcp_page):
        """enabled is True when start != end (normal pool)."""
        status = dhcp_page.get_dhcp_server_status()
        if status.pool_start != status.pool_end:
            assert status.enabled is True
        else:
            assert status.enabled is False


class TestReadLeases:
    """Verify lease listing works."""

    def test_list_leases(self, dhcp_page):
        dhcp_page.navigate()
        leases = dhcp_page.list_leases()
        assert isinstance(leases, list)
        print(f"\nFound {len(leases)} static DHCP leases")
        for lease in leases:
            print(f"  {lease.name}: {lease.mac} -> {lease.ip}")

    def test_list_leases_after_status_check(self, dhcp_page):
        """list_leases works after navigating for status."""
        dhcp_page.get_dhcp_server_status()
        dhcp_page.navigate()
        leases = dhcp_page.list_leases()
        assert isinstance(leases, list)


# ---------------------------------------------------------------------------
# Write tests — add/remove DUMMY lease, manipulate pool range
# Never touches existing leases. Always restores original state.
# ---------------------------------------------------------------------------

# Dummy lease: locally-administered MAC, high IP unlikely to conflict
_DUMMY_MAC = "02:00:DE:AD:BE:EF"
_DUMMY_IP = "192.168.0.249"
_DUMMY_NAME = "_test_dummy"


@pytest.mark.skipif(
    not os.environ.get("KABELBOX_WRITE_TEST"),
    reason="Set KABELBOX_WRITE_TEST=1 to run write tests",
)
class TestLeaseAddRemove:
    """Add and remove a dummy DHCP lease. Never touches real leases."""

    def _cleanup_dummy(self, dhcp_page):
        """Remove the dummy lease if present."""
        from arris.core.waits import settle
        dhcp_page.navigate()
        if dhcp_page.delete_lease_by_mac(_DUMMY_MAC):
            dhcp_page.apply()
            settle(8.0)

    def test_add_dummy_lease(self, dhcp_page):
        from arris.models.dhcp_lease import DHCPLease

        self._cleanup_dummy(dhcp_page)
        try:
            lease = DHCPLease(name=_DUMMY_NAME, mac=_DUMMY_MAC, ip=_DUMMY_IP)
            dhcp_page.add_lease(lease)
            dhcp_page.apply()
            time.sleep(3)

            dhcp_page.navigate()
            leases = dhcp_page.list_leases()
            found = [l for l in leases if l.mac == _DUMMY_MAC]
            assert len(found) == 1, f"Dummy not found. All: {[(l.mac, l.ip) for l in leases]}"
            assert found[0].ip == _DUMMY_IP
            print(f"\nAdded: {found[0]}")
        finally:
            self._cleanup_dummy(dhcp_page)

    def test_delete_dummy_lease(self, dhcp_page):
        from arris.models.dhcp_lease import DHCPLease

        self._cleanup_dummy(dhcp_page)
        try:
            dhcp_page.add_lease(DHCPLease(name=_DUMMY_NAME, mac=_DUMMY_MAC, ip=_DUMMY_IP))
            dhcp_page.apply()
            time.sleep(3)

            dhcp_page.navigate()
            assert dhcp_page.delete_lease_by_mac(_DUMMY_MAC)
            dhcp_page.apply()
            time.sleep(3)

            dhcp_page.navigate()
            leases = dhcp_page.list_leases()
            remaining = [l for l in leases if l.mac == _DUMMY_MAC]
            assert len(remaining) == 0, f"Dummy still present: {remaining}"
            print("\nDummy deleted successfully")
        finally:
            self._cleanup_dummy(dhcp_page)

    def test_add_is_idempotent(self, dhcp_page):
        from arris.models.dhcp_lease import DHCPLease

        self._cleanup_dummy(dhcp_page)
        try:
            lease = DHCPLease(name=_DUMMY_NAME, mac=_DUMMY_MAC, ip=_DUMMY_IP)
            dhcp_page.add_lease(lease)
            dhcp_page.apply()
            time.sleep(3)
            dhcp_page.add_lease(lease)

            dhcp_page.navigate()
            found = [l for l in dhcp_page.list_leases() if l.mac == _DUMMY_MAC]
            assert len(found) == 1, f"Expected 1 dummy, found {len(found)}"
            print("\nIdempotent add confirmed")
        finally:
            self._cleanup_dummy(dhcp_page)

    def test_existing_leases_untouched(self, dhcp_page):
        from arris.models.dhcp_lease import DHCPLease

        self._cleanup_dummy(dhcp_page)

        dhcp_page.navigate()
        before = {l.mac: l.ip for l in dhcp_page.list_leases() if l.mac != _DUMMY_MAC}

        try:
            dhcp_page.add_lease(DHCPLease(name=_DUMMY_NAME, mac=_DUMMY_MAC, ip=_DUMMY_IP))
            dhcp_page.apply()
            time.sleep(3)
            dhcp_page.navigate()
            after_add = {l.mac: l.ip for l in dhcp_page.list_leases() if l.mac != _DUMMY_MAC}
            assert before == after_add, f"Leases changed after add! {before} vs {after_add}"
        finally:
            self._cleanup_dummy(dhcp_page)

        dhcp_page.navigate()
        after_del = {l.mac: l.ip for l in dhcp_page.list_leases() if l.mac != _DUMMY_MAC}
        assert before == after_del, f"Leases changed after cleanup! {before} vs {after_del}"
        print(f"\n{len(before)} existing leases untouched")

    def test_rename_dummy_lease(self, dhcp_page):
        from arris.models.dhcp_lease import DHCPLease

        self._cleanup_dummy(dhcp_page)
        try:
            dhcp_page.add_lease(DHCPLease(name=_DUMMY_NAME, mac=_DUMMY_MAC, ip=_DUMMY_IP))
            dhcp_page.apply()
            time.sleep(3)
            dhcp_page.add_lease(DHCPLease(name="_test_renamed", mac=_DUMMY_MAC, ip=_DUMMY_IP))
            dhcp_page.apply()
            time.sleep(3)

            dhcp_page.navigate()
            found = [l for l in dhcp_page.list_leases() if l.mac == _DUMMY_MAC]
            assert len(found) == 1
            assert found[0].name == "_test_renamed", f"Got '{found[0].name}'"
            print(f"\nRename confirmed: {found[0].name}")
        finally:
            self._cleanup_dummy(dhcp_page)


@pytest.mark.skipif(
    not os.environ.get("KABELBOX_WRITE_TEST"),
    reason="Set KABELBOX_WRITE_TEST=1 to run write tests",
)
class TestDHCPPoolManipulation:
    """Test reading and writing the DHCP pool range.

    Always saves and restores the original pool values.
    """

    def test_set_pool_and_restore(self, dhcp_page):
        """Change the pool range, verify, then restore original.

        The Kabelbox rejects pool changes if any static lease IP falls
        outside the new range, so we use a range that still covers all
        static leases (just shrink the top end slightly).
        """
        original = dhcp_page.get_dhcp_server_status()
        print(f"\nOriginal pool: {original.pool_start} - {original.pool_end}")

        try:
            # Shrink top end by 2 — still covers all static leases in .2-.253 range
            result = dhcp_page.set_dhcp_pool("192.168.0.2", "192.168.0.251")
            assert result.pool_start == "192.168.0.2"
            assert result.pool_end == "192.168.0.251"
            print(f"Set pool to: {result.pool_start} - {result.pool_end}")
        finally:
            # Restore
            restored = dhcp_page.set_dhcp_pool(original.pool_start, original.pool_end)
            assert restored.pool_start == original.pool_start
            assert restored.pool_end == original.pool_end
            print(f"Restored pool: {restored.pool_start} - {restored.pool_end}")

    def test_set_pool_idempotent(self, dhcp_page):
        """Setting pool to current values is a fast no-op."""
        original = dhcp_page.get_dhcp_server_status()

        start = time.monotonic()
        result = dhcp_page.set_dhcp_pool(original.pool_start, original.pool_end)
        elapsed = time.monotonic() - start

        assert result.pool_start == original.pool_start
        assert result.pool_end == original.pool_end
        print(f"\nIdempotent set_dhcp_pool took {elapsed:.1f}s")

    def test_disable_and_reenable(self, dhcp_page):
        """Disable (delete leases + shrink pool) then re-enable.

        WARNING: This deletes all static DHCP leases on the router!
        They will NOT be restored — the Kabelbox requires lease deletion
        before allowing pool shrink. Only run this when you're actually
        migrating DHCP to another server.
        """
        pytest.skip(
            "Destructive: deletes all DHCP leases. "
            "Run manually with: kabelbox dhcp server-disable --yes"
        )

    def test_disable_idempotent(self, dhcp_page):
        """Calling disable when already disabled is a no-op."""
        pytest.skip(
            "Requires DHCP to already be disabled. "
            "Run after kabelbox dhcp server-disable --yes"
        )

    def test_leases_survive_pool_change(self, dhcp_page):
        """Static leases survive a pool range change (within valid range)."""
        dhcp_page.navigate()
        before = {l.mac: l.ip for l in dhcp_page.list_leases()}
        if not before:
            pytest.skip("No leases to test")

        original = dhcp_page.get_dhcp_server_status()

        try:
            # Shrink top end slightly — must still cover all static IPs
            dhcp_page.set_dhcp_pool("192.168.0.2", "192.168.0.251")
            dhcp_page.navigate()
            after = {l.mac: l.ip for l in dhcp_page.list_leases()}
            assert before == after, f"Leases changed! {before} vs {after}"
            print(f"\n{len(before)} leases survived pool change")
        finally:
            dhcp_page.set_dhcp_pool(original.pool_start, original.pool_end)
