"""CLI for arris-kabelbox — declarative ARRIS/Vodafone Kabelbox router management."""

from __future__ import annotations

import logging
import os
import sys

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

load_dotenv()

from .config import load_config
from .core.session import RouterSession

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )


def _get_wifi_password(env_name: str = "KABELBOX_WIFI_PASSWORD", prompt: str = "New WiFi passphrase") -> str:
    """A new WiFi passphrase, from the environment or a hidden prompt.

    Never a command-line argument: that would leave it in shell history and in
    the process list for anyone on the machine to read.
    """
    env = os.environ.get(env_name)
    if env:
        return env
    return click.prompt(prompt, hide_input=True, confirmation_prompt=True)


def _get_password(password: str | None) -> str:
    if password:
        return password
    env = os.environ.get("KABELBOX_PASSWORD")
    if env:
        return env
    return click.prompt("Router password", hide_input=True)


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("-H", "--host", default="192.168.0.1", help="Router IP address")
@click.option("-p", "--password", default=None, help="Router password (or KABELBOX_PASSWORD env)")
@click.option("--no-headless", is_flag=True, help="Show the browser window (disable headless mode)")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, host: str, password: str | None, no_headless: bool) -> None:
    """Declarative ARRIS/Vodafone Kabelbox router configuration management."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["host"] = host
    ctx.obj["password"] = password
    ctx.obj["verbose"] = verbose
    ctx.obj["headless"] = not no_headless


def _wifi_passphrases(config) -> tuple[str | None, str | None, str | None]:
    """Main, 5 GHz and guest passphrase for apply: each from its environment
    variable, else from the snapshot an export recorded, else None (left as
    the router has it). The router shows every passphrase in cleartext in a
    hidden <band>_clr field of WifiGeneral, which is what export saved."""
    w = config.wifi
    saved = ((config.snapshot or {}).get("WifiGeneral") or {}).get("fields") or {}

    def from_snapshot(key: str) -> str | None:
        v = saved.get(key)
        v = v.get("hidden") if isinstance(v, dict) else v
        return v or None

    return (
        os.environ.get(w.password_env) or from_snapshot("password_24g_clr"),
        os.environ.get(w.password_5g_env) or from_snapshot("password_5g_clr"),
        os.environ.get(w.guest_password_env) or from_snapshot("password_guest_clr"),
    )


# --- Port Forwarding ---


@cli.group("ports")
def ports_group() -> None:
    """Manage port forwarding rules."""


@ports_group.command("list")
@click.pass_context
def ports_list(ctx: click.Context) -> None:
    """List current port forwarding rules."""
    from .pages.port_forwarding import PortForwardingPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = PortForwardingPage(session)
        page.navigate()
        rules = page.list_rules()

    table = Table(title="Port Forwarding Rules")
    table.add_column("Name", style="cyan")
    table.add_column("Protocol")
    table.add_column("WAN Port", justify="right")
    table.add_column("LAN IP")
    table.add_column("LAN Port", justify="right")
    table.add_column("Enabled")

    for r in rules:
        status = "[green]on" if r.enabled else "[red]off"
        table.add_row(r.name, r.protocol, str(r.wan_port), r.lan_ip, str(r.lan_port), status)

    console.print(table)


@ports_group.command("add")
@click.option("--name", required=True)
@click.option("--protocol", type=click.Choice(["TCP", "UDP", "TCP/UDP"]), default="TCP")
@click.option("--wan-port", required=True, type=int)
@click.option("--lan-ip", required=True)
@click.option("--lan-port", type=int, default=None, help="Defaults to WAN port")
@click.pass_context
def ports_add(
    ctx: click.Context, name: str, protocol: str, wan_port: int, lan_ip: str, lan_port: int | None
) -> None:
    """Add a port forwarding rule."""
    from .models.port_rule import PortRule
    from .pages.port_forwarding import PortForwardingPage

    rule = PortRule(
        name=name, protocol=protocol, wan_port=wan_port,
        lan_port=lan_port or wan_port, lan_ip=lan_ip,
    )
    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = PortForwardingPage(session)
        page.navigate()
        page.add_rule(rule)
    console.print(f"[green]Added: {name} {protocol} {wan_port} -> {lan_ip}:{rule.lan_port}")


@ports_group.command("delete")
@click.option("--name", required=True)
@click.pass_context
def ports_delete(ctx: click.Context, name: str) -> None:
    """Delete a port forwarding rule by name."""
    from .pages.port_forwarding import PortForwardingPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = PortForwardingPage(session)
        page.navigate()
        if page.delete_rule(name):
            console.print(f"[green]Deleted: {name}")
        else:
            console.print(f"[yellow]Not found: {name}")


# --- DHCP ---


@cli.group("dhcp")
def dhcp_group() -> None:
    """Manage static DHCP reservations."""


@dhcp_group.command("list")
@click.pass_context
def dhcp_list(ctx: click.Context) -> None:
    """List static DHCP leases."""
    from .pages.dhcp import DHCPPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = DHCPPage(session)
        page.navigate()
        leases = page.list_leases()

    table = Table(title="Static DHCP Reservations")
    table.add_column("Name", style="cyan")
    table.add_column("MAC Address")
    table.add_column("IP Address", style="green")

    for lease in leases:
        table.add_row(lease.name, lease.mac, lease.ip)

    console.print(table)


@dhcp_group.command("add")
@click.option("--name", required=True)
@click.option("--mac", required=True)
@click.option("--ip", required=True)
@click.pass_context
def dhcp_add(ctx: click.Context, name: str, mac: str, ip: str) -> None:
    """Add a static DHCP reservation."""
    from .models.dhcp_lease import DHCPLease
    from .pages.dhcp import DHCPPage

    lease = DHCPLease(name=name, mac=mac, ip=ip)
    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = DHCPPage(session)
        page.add_lease(lease)
        page.apply()
    console.print(f"[green]Added: {name} {mac} -> {ip}")


@dhcp_group.command("delete")
@click.option("--mac", required=True, help="MAC address of the lease to delete")
@click.pass_context
def dhcp_delete(ctx: click.Context, mac: str) -> None:
    """Delete a static DHCP reservation by MAC address."""
    from .pages.dhcp import DHCPPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = DHCPPage(session)
        page.navigate()
        found = page.delete_lease_by_mac(mac)
        if found:
            page.apply()
            console.print(f"[green]Deleted: {mac.upper()}")
        else:
            console.print(f"[yellow]Not found: {mac.upper()}")


@dhcp_group.command("server")
@click.pass_context
def dhcp_server_status(ctx: click.Context) -> None:
    """Show DHCP server status."""
    from .pages.dhcp import DHCPPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = DHCPPage(session)
        status = page.get_dhcp_server_status()

    table = Table(title="DHCP Server Status")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    state = "[green]enabled" if status.enabled else "[red]disabled"
    table.add_row("DHCP Server", state)
    table.add_row("Pool Start", status.pool_start)
    table.add_row("Pool End", status.pool_end)
    table.add_row("Gateway", status.gateway)
    table.add_row("Netmask", status.netmask)

    console.print(table)


@dhcp_group.command("server-enable")
@click.pass_context
def dhcp_server_enable(ctx: click.Context) -> None:
    """Enable the DHCP server on the router."""
    from .pages.dhcp import DHCPPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = DHCPPage(session)
        status = page.set_dhcp_server_enabled(True)
    console.print(f"[green]DHCP server enabled (pool {status.pool_start} - {status.pool_end})")


@dhcp_group.command("server-disable")
@click.option("--yes", is_flag=True, help="Skip confirmation")
@click.pass_context
def dhcp_server_disable(ctx: click.Context, yes: bool) -> None:
    """Disable the DHCP server on the router.

    WARNING: Disabling DHCP means devices on this network will not get
    IP addresses automatically unless another DHCP server is running.
    """
    from .pages.dhcp import DHCPPage

    if not yes:
        if not click.confirm(
            "Disabling DHCP means no device will get an IP from this router. "
            "Make sure another DHCP server is running. Continue?"
        ):
            return

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = DHCPPage(session)
        status = page.set_dhcp_server_enabled(False)
    console.print("[green]DHCP server disabled")


# --- WiFi ---


@cli.group("wifi")
def wifi_group() -> None:
    """Manage WiFi settings."""


@wifi_group.command("status")
@click.pass_context
def wifi_status(ctx: click.Context) -> None:
    """Show current WiFi configuration."""
    from .pages.wifi import WifiGeneralPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = WifiGeneralPage(session)
        page.navigate()
        status = page.get_status()

    table = Table(title="WiFi Status")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Enabled", str(status.enabled))
    table.add_row("SSID" if not status.split_ssid else "SSID 2.4 GHz", status.ssid)
    if status.split_ssid:
        table.add_row("SSID 5 GHz", status.ssid_5g)
    table.add_row("Split SSID", str(status.split_ssid))
    table.add_row("Band Steering", str(status.band_steering))
    table.add_row("Broadcast 2.4 / 5 GHz", f"{status.broadcast_24} / {status.broadcast_5}")
    table.add_row("Guest WiFi", str(status.guest_wifi))
    if status.guest_wifi:
        table.add_row("Guest SSID", status.guest_ssid)
        table.add_row("Guest isolation", str(status.guest_isolate))
    table.add_row("Password Set", str(status.password_set))

    console.print(table)


@wifi_group.command("ssid")
@click.argument("name")
@click.pass_context
def wifi_ssid(ctx: click.Context, name: str) -> None:
    """Change the WiFi SSID."""
    from .pages.wifi import WifiGeneralPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = WifiGeneralPage(session)
        page.navigate()
        page.set_ssid(name)
        # The router often outlasts the apply wait, so success is read back
        # from the page rather than assumed from the click.
        page.navigate()
        status = page.get_status()
    if status.ssid != name:
        console.print(f"[red]SSID is still {status.ssid!r}, not {name!r}")
        raise SystemExit(1)
    console.print(f"[green]SSID is now: {status.ssid}")


@wifi_group.command("password")
@click.pass_context
def wifi_password(ctx: click.Context) -> None:
    """Change the WiFi passphrase (KABELBOX_WIFI_PASSWORD or prompt)."""
    from .pages.wifi import WifiGeneralPage

    pw = _get_password(ctx.obj["password"])
    new = _get_wifi_password()
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = WifiGeneralPage(session)
        page.navigate()
        page.set_password(new)
    console.print("[green]WiFi passphrase changed")


@wifi_group.command("set")
@click.option("--ssid", required=True, help="New network name")
@click.pass_context
def wifi_set(ctx: click.Context, ssid: str) -> None:
    """Change SSID and passphrase together, in one apply.

    Use this rather than `ssid` followed by `password` when both change: in
    between, the radios would broadcast the new name under the old passphrase.
    """
    from .pages.wifi import WifiGeneralPage

    pw = _get_password(ctx.obj["password"])
    new = _get_wifi_password()
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = WifiGeneralPage(session)
        page.navigate()
        page.set_ssid_and_password(ssid, new)
        page.navigate()
        status = page.get_status()
    console.print(f"[green]WiFi now {status.ssid!r}, passphrase set: {status.password_set}")


@wifi_group.command("config")
@click.option("--enable/--disable", "enabled", default=None, help="Turn WiFi on or off")
@click.option("--split/--no-split", "split_ssid", default=None, help="Separate names per band")
@click.option("--band-steering/--no-band-steering", default=None)
@click.option("--broadcast/--hide", "broadcast", default=None, help="Show or hide the network names")
@click.option("--guest/--no-guest", "guest_wifi", default=None, help="Guest WiFi on or off")
@click.option("--guest-isolate/--no-guest-isolate", default=None, help="Keep guest devices apart")
@click.option("--ssid", help="Network name (the 2.4 GHz one when split)")
@click.option("--ssid-5g", help="5 GHz network name, needs --split")
@click.option("--guest-ssid", help="Guest network name")
@click.option("--password", "change_password", is_flag=True,
              help="Change the passphrase (KABELBOX_WIFI_PASSWORD or prompt)")
@click.option("--password-5g", "change_password_5g", is_flag=True,
              help="Change the 5 GHz passphrase when split (KABELBOX_WIFI_PASSWORD_5G or prompt)")
@click.option("--guest-password", "change_guest_password", is_flag=True,
              help="Change the guest passphrase (KABELBOX_GUEST_WIFI_PASSWORD or prompt)")
@click.pass_context
def wifi_config(ctx: click.Context, change_password: bool, change_password_5g: bool,
                change_guest_password: bool, **settings) -> None:
    """Change any WiFi setting, all in one apply, and read the result back.

    Passphrases never go on the command line: each flag reads its own
    environment variable or prompts.
    """
    from .pages.wifi import WifiGeneralPage

    wanted = {k: v for k, v in settings.items() if v is not None}
    if change_password:
        wanted["password"] = _get_wifi_password()
    if change_password_5g:
        wanted["password_5g"] = _get_wifi_password("KABELBOX_WIFI_PASSWORD_5G", "New 5 GHz passphrase")
    if change_guest_password:
        wanted["guest_password"] = _get_wifi_password("KABELBOX_GUEST_WIFI_PASSWORD", "New guest passphrase")
    if not wanted:
        raise click.UsageError("nothing to change; see --help")

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = WifiGeneralPage(session)
        page.navigate()
        page.configure(**wanted)
        page.navigate()
        status = page.get_status()

    # Everything readable is checked against what was asked; passphrases the
    # page does not reveal are taken as staged once their popup saved.
    readable = {"enabled": "enabled", "split_ssid": "split_ssid", "band_steering": "band_steering",
                "guest_wifi": "guest_wifi", "guest_isolate": "guest_isolate", "ssid": "ssid",
                "ssid_5g": "ssid_5g", "guest_ssid": "guest_ssid"}
    wrong = [f"{k}: wanted {wanted[k]!r}, router has {getattr(status, f)!r}"
             for k, f in readable.items() if k in wanted and getattr(status, f) != wanted[k]]
    if "broadcast" in wanted and (status.broadcast_24, status.broadcast_5) != (wanted["broadcast"],) * 2:
        wrong.append(f"broadcast: wanted {wanted['broadcast']}, router has {status.broadcast_24} / {status.broadcast_5}")
    ctx.invoke(wifi_status)
    if wrong:
        for line in wrong:
            console.print(f"[red]{line}")
        raise SystemExit(1)


@wifi_group.command("mac-filter")
@click.pass_context
def wifi_mac_filter(ctx: click.Context) -> None:
    """List WiFi MAC filter entries."""
    from .pages.wifi import WifiMacFilterPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = WifiMacFilterPage(session)
        page.navigate()
        macs = page.list_allowed_macs()

    if macs:
        console.print("[bold]Allowed MACs:")
        for mac in macs:
            console.print(f"  {mac}")
    else:
        console.print("[yellow]No MAC filter entries (or filter disabled)")


# --- Firewall ---


@cli.group("firewall")
def firewall_group() -> None:
    """Manage firewall settings."""


@firewall_group.command("status")
@click.pass_context
def firewall_status(ctx: click.Context) -> None:
    """Show firewall status."""
    from .pages.firewall import FirewallPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = FirewallPage(session)
        page.navigate()
        status = page.get_status()

    console.print(f"Firewall: [{'green' if status.enabled else 'red'}]"
                  f"{'enabled' if status.enabled else 'DISABLED'}")
    if status.raw_fields:
        for key, val in status.raw_fields.items():
            if key not in ("applyButton", "cancelButton"):
                console.print(f"  {key}: {val}")


# --- Status ---


@cli.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show connected devices and router status."""
    from .pages.status import OverviewPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = OverviewPage(session)
        page.navigate()
        devices = page.get_connected_devices()

    table = Table(title="Connected Devices")
    table.add_column("Name", style="cyan")
    table.add_column("IP", style="green")
    table.add_column("MAC")
    table.add_column("Connection")
    table.add_column("Speed")

    for d in devices:
        table.add_row(d.name, d.ip, d.mac, d.connection, d.speed)

    console.print(table)


# --- DOCSIS ---


@cli.command("docsis")
@click.option("--all", "show_all", is_flag=True, help="List every channel, also unlocked ones")
@click.pass_context
def docsis_cmd(ctx: click.Context, show_all: bool) -> None:
    """Show cable sync: locked channels, signal levels and the WAN address.

    Exits 1 when the modem has no cable connection, so scripts can alert on it.
    """
    from .pages.status import DocsisPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = DocsisPage(session)
        page.navigate()
        st = page.get_status()

    ds_locked = sum(c.locked for c in st.downstream)
    us_locked = sum(c.locked for c in st.upstream)
    state = "[green]online" if st.online else "[red]NO CABLE CONNECTION"
    console.print(f"{state}[/]  WAN IPv4 {st.wan_ipv4 or '-'}  "
                  f"downstream {ds_locked}/{len(st.downstream)} locked  "
                  f"upstream {us_locked}/{len(st.upstream)} ranged")

    for title, chans, snr in (("Downstream", st.downstream, True), ("Upstream", st.upstream, False)):
        shown = chans if show_all else [c for c in chans if c.locked]
        if not shown:
            continue
        table = Table(title=title)
        for col in ("ID", "Type", "MHz", "Modulation", "Power"):
            table.add_column(col)
        if snr:
            table.add_column("SNR dB")
        table.add_column("Status")
        for c in shown:
            cells = [c.channel_id, c.channel_type, c.frequency_mhz, c.modulation, c.power]
            if snr:
                cells.append(c.snr_db)
            table.add_row(*cells, c.status)
        console.print(table)

    if not st.online:
        ctx.exit(1)


# --- Info ---


@cli.command("info")
@click.pass_context
def info_cmd(ctx: click.Context) -> None:
    """Show router hardware and firmware info."""
    from .pages.device import AboutPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = AboutPage(session)
        page.navigate()
        info = page.get_info()

    table = Table(title="Router Info")
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    for key, val in info.items():
        if key != "text" and len(str(val)) < 100:
            table.add_row(key, str(val))

    console.print(table)


# --- Event Log ---


@cli.command("log")
@click.pass_context
def log_cmd(ctx: click.Context) -> None:
    """Show router event log."""
    from .pages.device import EventLogPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = EventLogPage(session)
        page.navigate()
        entries = page.get_log_entries()

    table = Table(title="Event Log")
    table.add_column("Time", style="dim")
    table.add_column("Message")

    for entry in entries[:50]:  # Show last 50
        table.add_row(entry.get("time", ""), entry.get("message", ""))

    console.print(table)


# --- Phone (Telefon) ---


@cli.group("phone")
def phone_group() -> None:
    """Telephone menu: call history, numbers, settings."""


@phone_group.command("history")
@click.option("-n", "--limit", default=50, help="Max entries to show")
@click.pass_context
def phone_history(ctx: click.Context, limit: int) -> None:
    """Show the phone call history / log."""
    from .pages.phone import PhoneCallLogPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = PhoneCallLogPage(session)
        page.navigate()
        entries = page.get_entries()

    if not entries:
        console.print("[yellow]No call log entries found")
        return

    table = Table(title="Call History")
    table.add_column("Date", style="dim")
    table.add_column("Time", style="dim")
    table.add_column("Direction")
    table.add_column("Number", style="cyan")
    table.add_column("Duration", justify="right")

    colors = {"incoming": "green", "outgoing": "blue", "missed": "red"}
    for e in entries[:limit]:
        dir_text = f"[{colors[e.direction]}]{e.direction}" if e.direction in colors else (e.direction or "-")
        table.add_row(e.date or "-", e.time or "-", dir_text, e.number or "-", e.duration or "-")

    console.print(table)


@phone_group.command("numbers")
@click.pass_context
def phone_numbers(ctx: click.Context) -> None:
    """List configured phone numbers / SIP accounts."""
    from .pages.phone import PhoneNumbersPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = PhoneNumbersPage(session)
        page.navigate()
        numbers = page.list_numbers()

    if not numbers:
        console.print("[yellow]No phone numbers found")
        return

    table = Table(title="Phone Numbers")
    table.add_column("Port", justify="right")
    table.add_column("Number", style="cyan")
    table.add_column("Status")
    table.add_column("Registered")

    for n in numbers:
        state = "[green]yes" if n.registered else "[red]no"
        table.add_row(str(n.port), n.number, n.status or "-", state)

    console.print(table)


@phone_group.command("settings")
@click.pass_context
def phone_settings(ctx: click.Context) -> None:
    """Show phone settings."""
    from .pages.phone import PhoneSettingsPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = PhoneSettingsPage(session)
        page.navigate()
        settings = page.get_settings()

    if not settings:
        console.print("[yellow]No phone settings found")
        return

    table = Table(title="Phone Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    for key, val in settings.items():
        table.add_row(key, str(val))

    console.print(table)


# --- DynDNS ---


@cli.command("ddns")
@click.pass_context
def ddns_cmd(ctx: click.Context) -> None:
    """Show DynDNS configuration."""
    from .pages.network import DynDNSPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = DynDNSPage(session)
        page.navigate()
        config = page.get_config()

    table = Table(title="DynDNS Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Enabled", str(config.enabled))
    table.add_row("Provider", config.provider or "(none)")
    table.add_row("Hostname", config.hostname or "(none)")
    table.add_row("Username", config.username or "(none)")

    console.print(table)


# --- Apply (declarative) ---


@cli.command("apply")
@click.argument("config_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Show what would change without applying")
@click.pass_context
def apply_cmd(ctx: click.Context, config_file: str, dry_run: bool) -> None:
    """Apply a declarative configuration to the router."""
    config = load_config(config_file)
    host = config.host or ctx.obj["host"]

    desired_ports = [r.to_model() for r in config.port_forwarding]
    desired_dhcp = [l.to_model() for l in config.dhcp_reservations]

    if dry_run:
        console.print("[bold]Dry run — would apply:[/bold]")
        if desired_ports:
            console.print(f"\n[cyan]Port forwarding ({len(desired_ports)} rules):")
            for r in desired_ports:
                console.print(f"  {r.name}: {r.protocol} {r.wan_port} -> {r.lan_ip}:{r.lan_port}")
        if desired_dhcp:
            console.print(f"\n[cyan]DHCP reservations ({len(desired_dhcp)} leases):")
            for l in desired_dhcp:
                console.print(f"  {l.name}: {l.mac} -> {l.ip}")
        if config.dhcp_server:
            d = config.dhcp_server
            console.print(f"\n[cyan]DHCP server: {'on' if d.enabled else 'off'}, pool {d.pool_start} - {d.pool_end}")
        if config.wifi:
            w = config.wifi
            console.print(f"\n[cyan]WiFi: {w.model_dump(exclude={'password_env', 'password_5g_env', 'guest_password_env'})}")
            set_pws = [n for n, v in zip(("main", "5 GHz", "guest"), _wifi_passphrases(config)) if v]
            console.print(f"  passphrases set: {', '.join(set_pws) or 'none, they stay as they are'}")
        if config.firewall:
            console.print(f"\n[cyan]Firewall: {'on' if config.firewall.enabled else 'off'}")
        if config.snapshot:
            from .pages.snapshot import restore_all

            console.print("\n[cyan]Snapshot settings that differ on the router now:")
            pw = _get_password(ctx.obj["password"])
            with RouterSession(host, pw, headless=ctx.obj["headless"]) as session:
                diff = restore_all(session, config.snapshot, dry_run=True)
            for mid, changes in diff.items():
                console.print(f"  [cyan]{mid}[/]")
                for c in changes:
                    console.print(f"    {c}")
            if not diff:
                console.print("  none")
        return

    pw = _get_password(ctx.obj["password"])
    with RouterSession(host, pw, headless=ctx.obj["headless"]) as session:
        if desired_dhcp:
            from .pages.dhcp import DHCPPage

            console.print("\n[bold]Syncing DHCP reservations...[/bold]")
            page = DHCPPage(session)
            page.navigate()
            result = page.sync(desired_dhcp)
            console.print(
                f"  +{result['added']} -{result['deleted']} ={result['unchanged']}"
            )
            if result["errors"]:
                for err in result["errors"]:
                    console.print(f"  [red]Error: {err}")

        if desired_ports:
            from .pages.port_forwarding import PortForwardingPage

            console.print("\n[bold]Syncing port forwarding...[/bold]")
            page = PortForwardingPage(session)
            page.navigate()
            result = page.sync(desired_ports)
            console.print(
                f"  +{result['added']} -{result['deleted']} ={result['unchanged']}"
            )
            if result["errors"]:
                for err in result["errors"]:
                    console.print(f"  [red]Error: {err}")

        if config.dhcp_server:
            from .pages.dhcp import DHCPPage

            console.print("\n[bold]Setting the DHCP server...[/bold]")
            d = config.dhcp_server
            page = DHCPPage(session)
            page.navigate()
            current = page.get_dhcp_server_status()
            if (current.pool_start, current.pool_end) != (d.pool_start, d.pool_end):
                page.set_dhcp_pool(d.pool_start, d.pool_end)
            if current.enabled != d.enabled:
                page.set_dhcp_server_enabled(d.enabled)
            console.print("  ok")

        if config.wifi:
            from .pages.wifi import WifiGeneralPage

            console.print("\n[bold]Setting WiFi...[/bold]")
            w = config.wifi
            pw_main, pw_5g, pw_guest = _wifi_passphrases(config)
            page = WifiGeneralPage(session)
            page.navigate()
            page.configure(
                enabled=w.enabled, split_ssid=w.split_ssid, band_steering=w.band_steering,
                guest_wifi=w.guest_wifi, guest_isolate=w.guest_isolate if w.guest_wifi else None,
                ssid=w.ssid, ssid_5g=w.ssid_5g if w.split_ssid else None,
                broadcast=w.broadcast, guest_ssid=w.guest_ssid if w.guest_wifi else None,
                password=pw_main,
                password_5g=pw_5g if w.split_ssid else None,
                guest_password=pw_guest if w.guest_wifi else None,
            )
            console.print("  ok")

        if config.firewall:
            from .pages.firewall import FirewallPage

            console.print("\n[bold]Setting the firewall...[/bold]")
            page = FirewallPage(session)
            page.navigate()
            page.set_enabled(config.firewall.enabled)
            console.print("  ok")

        if config.snapshot:
            from .pages.snapshot import restore_all

            console.print("\n[bold]Restoring the remaining settings from the snapshot...[/bold]")
            for mid, changes in restore_all(session, config.snapshot, dry_run=False).items():
                console.print(f"  [cyan]{mid}[/]")
                for c in changes:
                    console.print(f"    {c}")

    console.print("\n[green]Done!")


# --- Export ---


@cli.command("export")
@click.argument("output", type=click.Path(dir_okay=False, writable=True))
@click.pass_context
def export_cmd(ctx: click.Context, output: str) -> None:
    """Write the router's whole configuration to a YAML file.

    The sections apply knows (port_forwarding, dhcp_reservations, dhcp_server,
    wifi, firewall) come out in their structured form. Everything else the
    menu shows lands under `snapshot`, page by page, which apply writes back
    field by field after the structured sections.
    The file is created readable by its owner only, since the snapshot can
    carry credentials (DynDNS, telephony).
    """
    import yaml

    from .pages.dhcp import DHCPPage
    from .pages.firewall import FirewallPage
    from .pages.port_forwarding import PortForwardingPage
    from .pages.snapshot import snapshot_all
    from .pages.wifi import WifiGeneralPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = PortForwardingPage(session)
        page.navigate()
        rules = page.list_rules()

        dhcp = DHCPPage(session)
        dhcp.navigate()
        leases = dhcp.list_leases()
        server = dhcp.get_dhcp_server_status()

        wifi_page = WifiGeneralPage(session)
        wifi_page.navigate()
        wifi = wifi_page.get_status()

        fw_page = FirewallPage(session)
        fw_page.navigate()
        firewall = fw_page.get_status()

        snapshot = snapshot_all(session)

    def rule(r) -> dict:
        d = {"name": r.name, "protocol": r.protocol, "wan_port": r.wan_port,
             "lan_port": r.lan_port, "lan_ip": r.lan_ip}
        if r.is_range:
            d["wan_port_end"] = r.wan_port_end
            d["lan_port_end"] = r.effective_lan_end
        if not r.enabled:
            d["enabled"] = False
        return d

    wifi_out = {
        "enabled": wifi.enabled, "ssid": wifi.ssid, "split_ssid": wifi.split_ssid,
        "band_steering": wifi.band_steering, "broadcast": wifi.broadcast_24 and wifi.broadcast_5,
        "guest_wifi": wifi.guest_wifi, "guest_isolate": wifi.guest_isolate,
    }
    if wifi.split_ssid:
        wifi_out["ssid_5g"] = wifi.ssid_5g
    if wifi.guest_ssid:
        wifi_out["guest_ssid"] = wifi.guest_ssid

    data = {
        "host": ctx.obj["host"],
        "port_forwarding": [rule(r) for r in rules],
        "dhcp_reservations": [{"name": l.name, "mac": l.mac, "ip": l.ip} for l in leases],
        "dhcp_server": {"enabled": server.enabled, "pool_start": server.pool_start,
                        "pool_end": server.pool_end},
        "wifi": wifi_out,
        "firewall": {"enabled": firewall.enabled},
        "snapshot": snapshot,
    }

    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, width=120)
    console.print(f"[green]Wrote {output}[/]: {len(rules)} port rules, {len(leases)} reservations, "
                  f"{len(snapshot)} pages in the snapshot")


# --- Operating mode ---


@cli.group("mode")
def mode_group() -> None:
    """Router or modem-only (bridge) operation."""


@mode_group.command("status")
@click.pass_context
def mode_status(ctx: click.Context) -> None:
    """Show whether the station runs as router or in bridge mode."""
    from .pages.modem import ModemModePage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = ModemModePage(session)
        page.navigate()
        console.print(page.get_mode())


def _switch_mode(ctx: click.Context, mode: str, yes: bool, warning: str) -> None:
    from .pages.modem import ModemModePage

    if not yes and not click.confirm(warning):
        return
    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = ModemModePage(session)
        page.navigate()
        if page.get_mode() == mode:
            console.print(f"Already in {mode} mode")
            return
        dialog = page.set_mode(mode)
    if dialog:
        console.print(f"[dim]Confirmed: {dialog}")
    console.print(f"[yellow]Station is rebooting into {mode} mode")


@mode_group.command("bridge")
@click.option("--yes", is_flag=True, help="Skip confirmation")
@click.pass_context
def mode_bridge(ctx: click.Context, yes: bool) -> None:
    """Switch to bridge mode: only LAN port 1 stays, carrying the public address."""
    _switch_mode(
        ctx, "bridge", yes,
        "Bridge mode stops the wifi and LAN ports 2-4, and the station reboots. Continue?",
    )


@mode_group.command("router")
@click.option("--yes", is_flag=True, help="Skip confirmation")
@click.pass_context
def mode_router(ctx: click.Context, yes: bool) -> None:
    """Switch back to router mode."""
    _switch_mode(ctx, "router", yes, "The station reboots into router mode. Continue?")


# --- Restart ---


@cli.command("restart")
@click.option("--yes", is_flag=True, help="Skip confirmation")
@click.pass_context
def restart_cmd(ctx: click.Context, yes: bool) -> None:
    """Restart the router."""
    if not yes:
        if not click.confirm("Are you sure you want to restart the router?"):
            return

    from .pages.device import RestartPage

    pw = _get_password(ctx.obj["password"])
    with RouterSession(ctx.obj["host"], pw, headless=ctx.obj["headless"]) as session:
        page = RestartPage(session)
        page.navigate()
        page.restart(confirm=True)
    console.print("[yellow]Router is restarting...")
