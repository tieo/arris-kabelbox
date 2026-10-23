"""Read every settings page the router's menu offers, for a full backup.

The structured pages (port forwarding, DHCP, WiFi, firewall) each have their
own reader; this module covers everything else generically, so a factory
reset loses nothing that was visible in the web UI. A page is recorded as its
form fields (inputs, selects, textareas, on/off switch divs) and the text of
its tables, keyed by element id.
"""

from __future__ import annotations

import logging
import re

from ..core.session import PAGE_ROUTES, RouterSession

log = logging.getLogger(__name__)

# Pages that only act or only show volatile counters, never settings.
_SKIP_MIDS = {"StatusRestart", "StatusDiagnosticUtility", "StatusEventLog", "PhoneCallLog"}

# Collects every route the menu links to, as "page&mid=Mid" strings for go().
_DISCOVER_JS = """
var out = {};
document.querySelectorAll("a[href*='mid=']").forEach(function (a) {
    var m = a.getAttribute("href").match(/\\?([^&#]+&mid=([A-Za-z0-9_]+))/);
    if (m) out[m[2]] = m[1];
});
return out;
"""

_DUMP_JS = """
var content = document.getElementById("content");
if (!content) return null;
var fields = {}, switches = {}, tables = {};
content.querySelectorAll("input, select, textarea").forEach(function (el, i) {
    if (el.type === "button" || el.type === "submit") return;
    var key = el.id || el.name || ("#" + i);
    var v;
    if (el.type === "checkbox" || el.type === "radio") v = el.checked;
    else if (el.tagName === "SELECT") v = {value: el.value,
        text: el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : ""};
    else v = el.value;
    var visible = el.getBoundingClientRect().height > 0;
    fields[key] = visible ? v : {hidden: v};
});
content.querySelectorAll("div.button").forEach(function (el) {
    if (el.id) switches[el.id] = el.classList.contains("button-on");
});
content.querySelectorAll("table").forEach(function (t, i) {
    var rows = [];
    for (var r = 0; r < t.rows.length; r++) {
        var row = [];
        for (var c = 0; c < t.rows[r].cells.length; c++)
            row.push(t.rows[r].cells[c].textContent.replace(/\\s+/g, " ").trim());
        if (row.join("").length) rows.push(row);
    }
    if (rows.length) tables[t.id || ("table" + i)] = rows;
});
return {fields: fields, switches: switches, tables: tables};
"""


def discover_routes(session: RouterSession) -> dict[str, str]:
    """Every page mid the menu links to, registered in the session's route
    table. Routes the tool knows but the menu does not link (PhoneNumbers
    without telephony, SettingsModem on firmware without a modem mode) open
    blank, so only linked pages count."""
    found = session.execute(_DISCOVER_JS) or {}
    for mid, route in found.items():
        PAGE_ROUTES.setdefault(mid, route)
    return dict(sorted(found.items()))


def snapshot_page(session: RouterSession, mid: str) -> dict | None:
    session.navigate(mid)
    return session.execute(_DUMP_JS)


def snapshot_all(session: RouterSession) -> dict[str, dict]:
    """Raw state of every settings page, keyed by mid. A failing page is
    recorded with its error instead of aborting the backup."""
    out: dict[str, dict] = {}
    for mid in discover_routes(session):
        if mid in _SKIP_MIDS or re.match(r"^Status(Docsis|Status|About)$", mid):
            continue
        try:
            out[mid] = snapshot_page(session, mid) or {}
        except Exception as e:  # one broken page must not lose the rest
            log.warning("Could not read %s: %s", mid, e)
            out[mid] = {"error": f"{type(e).__name__}: {e}"}
    return out


# Pages restore leaves alone: apply owns them through its structured sections
# (port forwarding, WiFi with its passphrase popups), they hold the admin
# password, or they only show state.
_RESTORE_SKIP = {"NetPortMapping", "WifiGeneral", "SettingsPassword", "Overview",
                 "StatusLan", "WifiRadar", "WifiRadar24", "WifiRadar5"}

# Compares the saved page with the live one and, unless dry, writes the
# difference: switches first, since they reveal the fields that depend on
# them, then selects (also the hidden ones behind Chosen widgets), then
# visible editable inputs and checkboxes. Fields saved under a positional
# key ("#3") have no stable identity and are left out, as is anything that
# names a password. "Add..." selects only pick the device an add-form
# pre-fills, and their options follow whatever is connected, so they are not
# settings either.
_RESTORE_JS = """
var saved = arguments[0], dry = arguments[1], changes = [];
function skip(key) { return key.charAt(0) === "#" || /pass|pwd|psk/i.test(key) || /^Add/.test(key); }
function plain(v) { return (v && typeof v === "object" && "hidden" in v) ? v.hidden : v; }

Object.keys(saved.switches || {}).forEach(function (id) {
    var el = document.getElementById(id);
    if (!el) return;
    var on = el.classList.contains("button-on");
    if (on !== saved.switches[id]) {
        changes.push("switch " + id + ": " + on + " -> " + saved.switches[id]);
        if (!dry) el.click();
    }
});

var fields = saved.fields || {};
Object.keys(fields).forEach(function (key) {
    if (skip(key)) return;
    var el = document.getElementById(key);
    if (!el || el.disabled || el.readOnly) return;
    var want = plain(fields[key]);
    if (el.tagName === "SELECT") {
        if (!want || typeof want !== "object" || el.value === want.value) return;
        changes.push("select " + key + ": " + el.value + " -> " + want.value + " (" + want.text + ")");
        if (!dry) {
            el.value = want.value;
            if (typeof jQuery !== "undefined") jQuery(el).trigger("chosen:updated").trigger("change");
            else el.dispatchEvent(new Event("change", {bubbles: true}));
        }
        return;
    }
    if (el.getBoundingClientRect().height === 0) return;
    if (el.type === "checkbox" || el.type === "radio") {
        if (typeof want !== "boolean" || el.checked === want) return;
        if (el.type === "radio" && !want) return;  // checking its sibling clears it
        changes.push(el.type + " " + key + ": " + el.checked + " -> " + want);
        if (!dry) el.click();
        return;
    }
    if (typeof want !== "string" || el.value === want) return;
    changes.push("input " + key + ": " + JSON.stringify(el.value) + " -> " + JSON.stringify(want));
    if (!dry) {
        el.value = want;
        el.dispatchEvent(new Event("input", {bubbles: true}));
        el.dispatchEvent(new Event("change", {bubbles: true}));
    }
});
return changes;
"""


def restore_page(session: RouterSession, mid: str, saved: dict, *, dry_run: bool) -> list[str]:
    """Bring one page back to its saved state, applying only when it differs."""
    session.navigate(mid)
    changes = session.execute(_RESTORE_JS, saved, dry_run) or []
    if changes and not dry_run:
        session.apply()
    return changes


def restore_all(session: RouterSession, snapshot: dict[str, dict], *, dry_run: bool) -> dict[str, list[str]]:
    """Restore every saved page the menu still offers. Returns the changes made
    (or, dry, the ones that would be), keyed by page."""
    routes = discover_routes(session)
    out: dict[str, list[str]] = {}
    for mid, saved in snapshot.items():
        if mid in _RESTORE_SKIP or "error" in saved:
            continue
        if mid not in routes:
            out[mid] = ["page not in the menu, skipped"]
            continue
        try:
            changes = restore_page(session, mid, saved, dry_run=dry_run)
        except Exception as e:  # one page failing must not stop the rest
            log.warning("Could not restore %s: %s", mid, e)
            changes = [f"ERROR {type(e).__name__}: {e}"]
        if changes:
            out[mid] = changes
    return out
