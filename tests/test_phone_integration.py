"""Integration tests for the telephone menu — runs against a real Kabelbox.

The phone pages (call history, numbers, settings) are READ-ONLY, so every
test here only needs KABELBOX_PASSWORD — there is no write-test tier.

Requires:
  - KABELBOX_PASSWORD env var set
  - Router reachable at 192.168.0.1 (or KABELBOX_HOST)
  - Firefox + geckodriver installed

Run with:
  KABELBOX_PASSWORD=xxx pytest tests/test_phone_integration.py -v -s
"""

from __future__ import annotations

import os
import re

import pytest

from arris.core.session import RouterSession
from arris.pages.phone import (
    CallLogEntry,
    PhoneCallLogPage,
    PhoneNumber,
    PhoneNumbersPage,
    PhoneSettingsPage,
)


# ---------------------------------------------------------------------------
# Skip unless explicitly opted in (read-only — only needs the password)
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not os.environ.get("KABELBOX_PASSWORD"),
    reason="Set KABELBOX_PASSWORD to run integration tests",
)

_IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_DURATION_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_VALID_DIRECTIONS = {"incoming", "outgoing", "missed", ""}


# ---------------------------------------------------------------------------
# Fixtures — single browser session shared across the module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def session():
    host = os.environ.get("KABELBOX_HOST", "192.168.0.1")
    password = os.environ.get("KABELBOX_PASSWORD", "")
    with RouterSession(host, password, headless=True) as s:
        yield s


@pytest.fixture(scope="module")
def call_log_page(session):
    page = PhoneCallLogPage(session)
    page.navigate()
    return page


@pytest.fixture(scope="module")
def numbers_page(session):
    page = PhoneNumbersPage(session)
    page.navigate()
    return page


@pytest.fixture(scope="module")
def settings_page(session):
    page = PhoneSettingsPage(session)
    page.navigate()
    return page


# ---------------------------------------------------------------------------
# Call history
# ---------------------------------------------------------------------------


class TestCallHistory:
    """Read the phone call log / history."""

    def test_navigate_does_not_raise(self, session):
        PhoneCallLogPage(session).navigate()

    def test_get_entries_returns_list(self, call_log_page):
        entries = call_log_page.get_entries()
        assert isinstance(entries, list)
        print(f"\nFound {len(entries)} call log entries")
        for e in entries[:20]:
            print(f"  {e.time} | {e.direction or '-':8} | {e.number or '-':16} | {e.duration or '-'}")

    def test_entries_are_dataclass(self, call_log_page):
        for e in call_log_page.get_entries():
            assert isinstance(e, CallLogEntry)

    def test_every_entry_has_date_and_time(self, call_log_page):
        """Date is non-empty (may be a relative label like 'Heute'); time is HH:MM."""
        for e in call_log_page.get_entries():
            assert e.date, f"Empty date: {e}"
            assert e.time and ":" in e.time, f"Time not HH:MM: {e.time!r}"
            assert any(ch.isdigit() for ch in e.time), f"Time has no digit: {e.time!r}"

    def test_every_entry_has_a_known_direction(self, call_log_page):
        """Real call rows always carry a direction icon — none should be blank."""
        entries = call_log_page.get_entries()
        if not entries:
            pytest.skip("Call log empty")
        for e in entries:
            assert e.direction in {"incoming", "outgoing", "missed"}, f"No direction: {e}"

    def test_directions_are_known_values(self, call_log_page):
        for e in call_log_page.get_entries():
            assert e.direction in _VALID_DIRECTIONS, f"Unknown direction: {e.direction!r}"

    def test_durations_well_formed_when_present(self, call_log_page):
        """A duration, if scraped, must look like M:SS or H:MM:SS."""
        for e in call_log_page.get_entries():
            if e.duration:
                assert _DURATION_RE.match(e.duration), f"Bad duration: {e.duration!r}"

    def test_numbers_contain_digits_when_present(self, call_log_page):
        for e in call_log_page.get_entries():
            if e.number:
                assert any(ch.isdigit() for ch in e.number), f"Number has no digit: {e.number!r}"

    def test_repeat_read_is_consistent(self, call_log_page):
        """Two reads without navigation return the same entries."""
        a = call_log_page.get_entries()
        b = call_log_page.get_entries()
        assert a == b, "Call log changed between two consecutive reads"

    def test_survives_renavigation(self, session):
        """Navigating away and back yields a stable entry count."""
        page = PhoneCallLogPage(session)
        page.navigate()
        first = len(page.get_entries())
        PhoneNumbersPage(session).navigate()
        page.navigate()
        second = len(page.get_entries())
        assert first == second, f"Entry count changed across renavigation: {first} -> {second}"

    def test_raw_text_available(self, call_log_page):
        """Raw text fallback is non-None (may be empty on an empty log)."""
        raw = call_log_page.get_raw_text()
        assert isinstance(raw, str)
        print(f"\nRaw call-log text length: {len(raw)}")

    def test_scraped_entries_appear_in_raw_text(self, call_log_page):
        """Sanity: a scraped number should be findable in the raw page text."""
        entries = call_log_page.get_entries()
        raw = call_log_page.get_raw_text()
        for e in entries[:5]:
            if e.number:
                assert e.number in raw, f"Scraped number {e.number!r} not in raw text"

    def test_entry_count_matches_delete_checkboxes(self, call_log_page, session):
        """One scraped entry per per-call delete checkbox (del0, del1, ...).

        Counts only numbered del checkboxes — the page also has a
        'deletePopupButton' which shares the 'del' prefix.
        """
        n_checkboxes = session.execute(
            "return Array.prototype.filter.call("
            "  document.querySelectorAll(\"#content input[type='checkbox']\"),"
            "  function(c){ return /^del\\d+$/.test(c.id); }).length;"
        )
        assert len(call_log_page.get_entries()) == n_checkboxes, (
            f"{len(call_log_page.get_entries())} entries vs {n_checkboxes} checkboxes"
        )


# ---------------------------------------------------------------------------
# Phone numbers / SIP accounts
# ---------------------------------------------------------------------------


class TestPhoneNumbers:
    """Read configured phone numbers."""

    def test_navigate_does_not_raise(self, session):
        PhoneNumbersPage(session).navigate()

    def test_list_returns_list(self, numbers_page):
        numbers = numbers_page.list_numbers()
        assert isinstance(numbers, list)
        print(f"\nFound {len(numbers)} phone numbers")
        for n in numbers:
            print(f"  port{n.port} | {n.number:16} | {n.status or '-':16} | registered={n.registered}")

    def test_entries_are_dataclass(self, numbers_page):
        for n in numbers_page.list_numbers():
            assert isinstance(n, PhoneNumber)

    def test_each_number_has_digits(self, numbers_page):
        """Empty slots are skipped, so every listed number has digits."""
        for n in numbers_page.list_numbers():
            assert n.number, f"Empty number leaked through: {n}"
            assert any(ch.isdigit() for ch in n.number), f"Number has no digit: {n.number!r}"

    def test_registered_is_bool(self, numbers_page):
        for n in numbers_page.list_numbers():
            assert isinstance(n.registered, bool)

    def test_port_is_positive_int(self, numbers_page):
        for n in numbers_page.list_numbers():
            assert isinstance(n.port, int) and n.port >= 1, f"Bad port: {n}"

    def test_registered_implies_status_text(self, numbers_page):
        """A registered account exposes a non-empty status string."""
        for n in numbers_page.list_numbers():
            if n.registered:
                assert n.status, f"Registered but no status text: {n}"

    def test_repeat_read_is_consistent(self, numbers_page):
        assert numbers_page.list_numbers() == numbers_page.list_numbers()


# ---------------------------------------------------------------------------
# Phone settings
# ---------------------------------------------------------------------------


class TestPhoneSettings:
    """Read phone settings key/value snapshot."""

    def test_navigate_does_not_raise(self, session):
        PhoneSettingsPage(session).navigate()

    def test_get_settings_returns_dict(self, settings_page):
        settings = settings_page.get_settings()
        assert isinstance(settings, dict)
        print(f"\nFound {len(settings)} phone settings")
        for k, v in settings.items():
            print(f"  {k} = {v}")

    def test_keys_are_strings(self, settings_page):
        for k in settings_page.get_settings():
            assert isinstance(k, str) and k, f"Bad settings key: {k!r}"

    def test_no_button_fields_leaked(self, settings_page):
        """get_settings() must exclude button inputs."""
        for k in settings_page.get_settings():
            assert "button" not in k.lower(), f"Button field leaked into settings: {k}"

    def test_repeat_read_is_consistent(self, settings_page):
        assert settings_page.get_settings() == settings_page.get_settings()
