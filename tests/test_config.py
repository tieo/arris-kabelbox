"""Tests for config loading and validation."""

import pytest
import tempfile
from pathlib import Path

from arris.config import load_config, RouterConfig


def _write_yaml(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


class TestConfigValidation:
    def test_empty_config(self):
        path = _write_yaml("")
        config = load_config(path)
        assert config.host == "192.168.0.1"
        assert config.port_forwarding == []
        assert config.dhcp_reservations == []

    def test_valid_config(self):
        path = _write_yaml("""
host: "10.0.0.1"
port_forwarding:
  - name: http
    protocol: TCP
    wan_port: 80
    lan_ip: "10.0.0.100"
dhcp_reservations:
  - name: server
    mac: "AA:BB:CC:DD:EE:FF"
    ip: "10.0.0.100"
""")
        config = load_config(path)
        assert config.host == "10.0.0.1"
        assert len(config.port_forwarding) == 1
        assert len(config.dhcp_reservations) == 1

        rule = config.port_forwarding[0].to_model()
        assert rule.name == "http"
        assert rule.wan_port == 80
        assert rule.lan_port == 80  # defaults to wan_port

        lease = config.dhcp_reservations[0].to_model()
        assert lease.mac == "AA:BB:CC:DD:EE:FF"

    def test_duplicate_macs_rejected(self):
        path = _write_yaml("""
dhcp_reservations:
  - name: a
    mac: "AA:BB:CC:DD:EE:FF"
    ip: "192.168.0.10"
  - name: b
    mac: "AA:BB:CC:DD:EE:FF"
    ip: "192.168.0.11"
""")
        with pytest.raises(Exception, match="Duplicate MAC"):
            load_config(path)

    def test_duplicate_ips_rejected(self):
        path = _write_yaml("""
dhcp_reservations:
  - name: a
    mac: "AA:BB:CC:DD:EE:FF"
    ip: "192.168.0.10"
  - name: b
    mac: "11:22:33:44:55:66"
    ip: "192.168.0.10"
""")
        with pytest.raises(Exception, match="Duplicate IP"):
            load_config(path)

    def test_duplicate_ports_rejected(self):
        path = _write_yaml("""
port_forwarding:
  - name: a
    protocol: TCP
    wan_port: 80
    lan_ip: "192.168.0.10"
  - name: b
    protocol: TCP
    wan_port: 80
    lan_ip: "192.168.0.20"
""")
        with pytest.raises(Exception, match="Duplicate port"):
            load_config(path)

    def test_invalid_protocol_rejected(self):
        path = _write_yaml("""
port_forwarding:
  - name: bad
    protocol: SCTP
    wan_port: 80
    lan_ip: "192.168.0.10"
""")
        with pytest.raises(Exception, match="Invalid protocol"):
            load_config(path)

    def test_lan_port_defaults_to_wan(self):
        path = _write_yaml("""
port_forwarding:
  - name: http
    wan_port: 80
    lan_ip: "192.168.0.10"
""")
        config = load_config(path)
        rule = config.port_forwarding[0].to_model()
        assert rule.lan_port == 80
