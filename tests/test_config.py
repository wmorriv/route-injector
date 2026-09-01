"""Tests for config loading and validation."""

import pytest
import yaml
from pathlib import Path

from route_tool.config import load_config, RouteToolConfig, BgpConfig


MINIMAL_CONFIG = {
    "bgp": {
        "local_as": 65001,
        "peer_address": "10.0.0.1",
        "peer_as": 65000,
        "router_id": "10.0.0.2",
        "local_address": "10.0.0.2",
    }
}


def _write_config(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return p


def test_minimal_config(tmp_path):
    cfg = load_config(_write_config(tmp_path, MINIMAL_CONFIG))
    assert cfg.bgp.local_as == 65001
    assert cfg.bgp.peer_address == "10.0.0.1"
    assert cfg.bgp.hold_time == 90


def test_full_config(tmp_path):
    data = {
        **MINIMAL_CONFIG,
        "routes": {
            "ipv4": {"enabled": True, "count": 500, "base_prefix": "198.51.100.0/24"},
            "ipv6": {"enabled": True, "count": 100, "base_prefix": "2001:db8::/32"},
        },
        "flapping": {
            "enabled": True,
            "percentage": 20,
            "interval_sec": 10,
            "pattern": "burst",
            "address_families": ["ipv4"],
            "burst_size": 25,
        },
    }
    cfg = load_config(_write_config(tmp_path, data))
    assert cfg.routes.ipv4.enabled is True
    assert cfg.routes.ipv4.count == 500
    assert cfg.routes.ipv6.enabled is True
    assert cfg.flapping.pattern.value == "burst"
    assert cfg.flapping.burst_size == 25


def test_invalid_peer_address(tmp_path):
    data = {**MINIMAL_CONFIG}
    data["bgp"] = {**data["bgp"], "peer_address": "not-an-ip"}
    with pytest.raises(Exception):
        load_config(_write_config(tmp_path, data))


def test_invalid_as_number(tmp_path):
    data = {**MINIMAL_CONFIG}
    data["bgp"] = {**data["bgp"], "local_as": 0}
    with pytest.raises(Exception):
        load_config(_write_config(tmp_path, data))


def test_flap_afi_not_enabled(tmp_path):
    data = {
        **MINIMAL_CONFIG,
        "routes": {"ipv4": {"enabled": False}},
        "flapping": {
            "enabled": True,
            "address_families": ["ipv4"],
        },
    }
    with pytest.raises(Exception, match="not enabled"):
        load_config(_write_config(tmp_path, data))


def test_cli_overrides(tmp_path):
    data = {
        **MINIMAL_CONFIG,
        "routes": {
            "ipv4": {"enabled": True, "count": 100},
            "vpnv4": {"enabled": True, "count": 100},
        },
        "flapping": {"enabled": True, "address_families": ["ipv4"]},
    }
    overrides = {
        "peer_address": "192.168.1.1",
        "count": 5000,
        "no_flap": True,
    }
    cfg = load_config(_write_config(tmp_path, data), overrides)
    assert cfg.bgp.peer_address == "192.168.1.1"
    assert cfg.routes.ipv4.count == 5000
    assert cfg.routes.vpnv4.count == 5000
    assert cfg.flapping.enabled is False


def test_invalid_rd_format(tmp_path):
    data = {
        **MINIMAL_CONFIG,
        "routes": {
            "vpnv4": {"enabled": True, "rd": "bad-rd"},
        },
    }
    with pytest.raises(Exception, match="RD must be"):
        load_config(_write_config(tmp_path, data))


def test_invalid_flap_afi(tmp_path):
    data = {
        **MINIMAL_CONFIG,
        "flapping": {
            "enabled": True,
            "address_families": ["bgpls"],
        },
    }
    with pytest.raises(Exception, match="Invalid address family"):
        load_config(_write_config(tmp_path, data))
