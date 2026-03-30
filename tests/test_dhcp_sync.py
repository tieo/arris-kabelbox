"""Unit tests for DHCPPage.sync two-phase logic.

Uses mocks to simulate the router DOM — no browser required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from arris.models.dhcp_lease import DHCPLease
from arris.pages.dhcp import DHCPPage


def _make_page(current_leases: list[DHCPLease]) -> tuple[DHCPPage, MagicMock]:
    """Build a DHCPPage with a mocked session.

    The page will return `current_leases` on the first list_leases() call
    (after phase-1 navigate) and an empty list on subsequent calls
    (simulating a fully-cleared router state after phase-1 apply),
    updated by whatever was "added" in-place.

    For simplicity, _add_lease_in_place and _rename_lease are also mocked.
    """
    session = MagicMock()
    page = DHCPPage(session)
    return page, session


def _make_lease(name: str, mac: str, ip: str) -> DHCPLease:
    return DHCPLease(name=name, mac=mac, ip=ip)


class TestSyncPhaseLogic:
    """Test that sync calls delete/add in the right order and counts correctly."""

    def _run_sync(
        self,
        current: list[DHCPLease],
        desired: list[DHCPLease],
        *,
        after_delete: list[DHCPLease] | None = None,
    ) -> tuple[dict, list[str]]:
        """
        Run sync with mocked page internals.

        after_delete: what list_leases returns after phase-1 apply.
                      Defaults to only the leases in desired that were in
                      current and didn't need changing.
        """
        page, session = _make_page(current)

        calls: list[str] = []

        # list_leases: return current on first call, after_delete on second
        if after_delete is None:
            desired_by_mac = {l.mac: l for l in desired}
            current_by_mac = {l.mac: l for l in current}
            after_delete = [
                cur for mac, cur in current_by_mac.items()
                if mac in desired_by_mac and desired_by_mac[mac].ip == cur.ip
            ]

        list_returns = [current, after_delete, after_delete]  # extra for verify
        list_call_count = [0]

        def fake_list_leases():
            idx = list_call_count[0]
            list_call_count[0] += 1
            return list_returns[idx] if idx < len(list_returns) else after_delete

        def fake_delete(mac):
            calls.append(f"delete:{mac}")
            return True

        def fake_add(lease, max_attempts=3):
            calls.append(f"add:{lease.mac}:{lease.ip}")

        def fake_rename(mac, name):
            calls.append(f"rename:{mac}:{name}")
            return True

        def fake_apply():
            calls.append("apply")

        def fake_navigate():
            calls.append("navigate")

        page.list_leases = fake_list_leases
        page.delete_lease_by_mac = fake_delete
        page._add_lease_in_place = fake_add
        page._rename_lease = fake_rename
        page.apply = fake_apply
        page.navigate = fake_navigate

        result = page.sync(desired)
        return result, calls

    def test_no_changes_needed(self):
        """All leases already correct — no deletes or adds."""
        leases = [_make_lease("PC", "AA:BB:CC:DD:EE:01", "192.168.0.10")]
        result, calls = self._run_sync(leases, leases, after_delete=leases)

        assert result["added"] == 0
        assert result["deleted"] == 0
        assert result["unchanged"] == 1
        assert "apply" not in calls  # no changes = no apply

    def test_add_new_lease(self):
        """Desired has a lease not in current — should add it."""
        desired = [_make_lease("PC", "AA:BB:CC:DD:EE:01", "192.168.0.10")]
        result, calls = self._run_sync([], desired, after_delete=[])

        assert result["added"] == 1
        assert result["deleted"] == 0
        assert "add:AA:BB:CC:DD:EE:01:192.168.0.10" in calls
        # apply called once after adds
        assert calls.count("apply") == 1

    def test_delete_stale_lease(self):
        """Current has a lease not in desired — should delete it."""
        stale = _make_lease("Old", "AA:BB:CC:DD:EE:FF", "192.168.0.99")
        result, calls = self._run_sync([stale], [], after_delete=[])

        assert result["deleted"] == 1
        assert result["added"] == 0
        assert "delete:AA:BB:CC:DD:EE:FF" in calls
        # apply called once after deletes
        assert calls.count("apply") == 1

    def test_ip_conflict_resolved(self):
        """Old entry owns .10, new entry wants .10, old entry moves to .12.

        Phase 1 must delete the old entry (wrong IP) before adding the new one.
        Phase 2 adds both at their correct IPs without navigating between.
        """
        old_entry = _make_lease("PC-dock", "CC:96:E5:9B:0C:6F", "192.168.0.10")
        desired = [
            _make_lease("PC-builtin", "CC:96:E5:4D:8C:86", "192.168.0.10"),
            _make_lease("PC-dock", "CC:96:E5:9B:0C:6F", "192.168.0.12"),
        ]

        result, calls = self._run_sync([old_entry], desired, after_delete=[])

        # Phase 1 must delete old_entry (its IP .10 is claimed by builtin, and
        # its own desired IP changed from .10 to .12)
        assert "delete:CC:96:E5:9B:0C:6F" in calls

        # Phase 2 must add both
        assert f"add:CC:96:E5:4D:8C:86:192.168.0.10" in calls
        assert f"add:CC:96:E5:9B:0C:6F:192.168.0.12" in calls

        # delete comes before any add
        del_idx = calls.index("delete:CC:96:E5:9B:0C:6F")
        add_builtin_idx = calls.index("add:CC:96:E5:4D:8C:86:192.168.0.10")
        assert del_idx < add_builtin_idx

        # apply after deletes, apply after adds
        assert result["deleted"] == 1
        assert result["added"] == 2

    def test_rename_only(self):
        """Lease has right IP but wrong name — rename, no delete/add."""
        current = [_make_lease("OldName", "AA:BB:CC:DD:EE:01", "192.168.0.10")]
        desired = [_make_lease("NewName", "AA:BB:CC:DD:EE:01", "192.168.0.10")]
        result, calls = self._run_sync(current, desired, after_delete=current)

        assert result["renamed"] == 1
        assert result["deleted"] == 0
        assert result["added"] == 0
        assert "rename:AA:BB:CC:DD:EE:01:NewName" in calls

    def test_no_spurious_apply_when_nothing_changes(self):
        """apply() must NOT be called when there's nothing to change."""
        leases = [_make_lease("A", "AA:BB:CC:DD:EE:01", "192.168.0.10")]
        result, calls = self._run_sync(leases, leases, after_delete=leases)
        assert "apply" not in calls

    def test_phase1_apply_called_before_phase2_adds(self):
        """apply after deletes must come before any adds."""
        old = _make_lease("Old", "AA:BB:CC:DD:EE:FF", "192.168.0.10")
        new = _make_lease("New", "11:22:33:44:55:66", "192.168.0.10")
        result, calls = self._run_sync([old], [new], after_delete=[])

        apply_idx = next(i for i, c in enumerate(calls) if c == "apply")
        add_idx = next(i for i, c in enumerate(calls) if c.startswith("add:"))
        assert apply_idx < add_idx

    def test_squatter_removed(self):
        """An entry with a different MAC that occupies an IP we want is deleted."""
        squatter = _make_lease("Squatter", "DE:AD:BE:EF:00:01", "192.168.0.10")
        desired = [_make_lease("PC", "AA:BB:CC:DD:EE:01", "192.168.0.10")]
        result, calls = self._run_sync([squatter], desired, after_delete=[])

        assert "delete:DE:AD:BE:EF:00:01" in calls
        assert result["deleted"] == 1


class TestSyncErrors:
    """Test error handling in sync."""

    def test_delete_failure_recorded(self):
        """If delete raises, error is recorded and sync continues."""
        stale = _make_lease("Bad", "AA:BB:CC:DD:EE:FF", "192.168.0.99")
        page, _ = _make_page([stale])
        page.navigate = MagicMock()
        page.apply = MagicMock()
        page.list_leases = MagicMock(return_value=[stale])
        page.delete_lease_by_mac = MagicMock(side_effect=RuntimeError("boom"))
        page._add_lease_in_place = MagicMock()
        page._rename_lease = MagicMock()

        result = page.sync([])

        assert len(result["errors"]) == 1
        assert "delete" in result["errors"][0]

    def test_add_failure_recorded(self):
        """If add raises, error is recorded and sync continues."""
        desired = [_make_lease("PC", "AA:BB:CC:DD:EE:01", "192.168.0.10")]
        page, _ = _make_page([])
        page.navigate = MagicMock()
        page.apply = MagicMock()

        call_count = [0]
        def fake_list():
            call_count[0] += 1
            return []
        page.list_leases = fake_list
        page.delete_lease_by_mac = MagicMock()
        page._add_lease_in_place = MagicMock(side_effect=RuntimeError("popup stuck"))
        page._rename_lease = MagicMock()

        result = page.sync(desired)

        assert len(result["errors"]) >= 1
        assert any("add" in e for e in result["errors"])
