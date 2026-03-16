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
        page.navigate()
        page.add_lease(lease)
        page.apply()
    console.print(f"[green]Added: {name} {mac} -> {ip}")


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
    table.add_row("SSID", status.ssid)
    table.add_row("Split SSID", str(status.split_ssid))
    table.add_row("Band Steering", str(status.band_steering))
    table.add_row("Guest WiFi", str(status.guest_wifi))
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
    console.print(f"[green]SSID changed to: {name}")


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

    console.print("\n[green]Done!")


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
