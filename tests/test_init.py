"""Tests for the route-tool init command."""

import yaml
from click.testing import CliRunner

from route_tool.cli import cli
from route_tool.config import RouteToolConfig


def _build_input(*answers):
    return "\n".join(str(a) for a in answers) + "\n"


def test_init_defaults(tmp_path):
    output = tmp_path / "config.yaml"
    runner = CliRunner()
    inp = _build_input(
        65001,       # local_as
        "10.0.0.2",  # router_id
        "",          # local_address (accept default = router_id)
        "10.0.0.1",  # peer_address
        65000,       # peer_as
        "Y",         # ipv4
        "N",         # ipv6
        "N",         # vpnv4
        "N",         # vpnv6
        100,         # ipv4 count
        "N",         # flapping
    )
    result = runner.invoke(cli, ["init", str(output)], input=inp)
    assert result.exit_code == 0, result.output

    data = yaml.safe_load(output.read_text())
    cfg = RouteToolConfig(**data)
    assert cfg.bgp.local_as == 65001
    assert cfg.bgp.peer_address == "10.0.0.1"
    assert cfg.bgp.local_address == "10.0.0.2"
    assert cfg.routes.ipv4.enabled is True
    assert cfg.routes.ipv6.enabled is False
    assert cfg.flapping.enabled is False


def test_init_all_afis(tmp_path):
    output = tmp_path / "config.yaml"
    runner = CliRunner()
    inp = _build_input(
        65001, "10.0.0.2", "", "10.0.0.1", 65000,
        "Y", "Y", "Y", "Y",  # all AFIs
        500,   # ipv4 count
        200,   # ipv6 count
        1000,  # vpnv4 count
        300,   # vpnv6 count
        "N",   # flapping
    )
    result = runner.invoke(cli, ["init", str(output)], input=inp)
    assert result.exit_code == 0, result.output

    data = yaml.safe_load(output.read_text())
    cfg = RouteToolConfig(**data)
    assert cfg.routes.ipv4.enabled is True
    assert cfg.routes.ipv4.count == 500
    assert cfg.routes.ipv6.enabled is True
    assert cfg.routes.ipv6.count == 200
    assert cfg.routes.vpnv4.enabled is True
    assert cfg.routes.vpnv4.count == 1000
    assert cfg.routes.vpnv6.enabled is True
    assert cfg.routes.vpnv6.count == 300


def test_init_with_flapping(tmp_path):
    output = tmp_path / "config.yaml"
    runner = CliRunner()
    inp = _build_input(
        65001, "10.0.0.2", "", "10.0.0.1", 65000,
        "Y", "N", "N", "N",
        100,
        "Y",   # flapping enabled
        20,    # percentage
        60,    # interval
    )
    result = runner.invoke(cli, ["init", str(output)], input=inp)
    assert result.exit_code == 0, result.output

    data = yaml.safe_load(output.read_text())
    cfg = RouteToolConfig(**data)
    assert cfg.flapping.enabled is True
    assert cfg.flapping.percentage == 20
    assert cfg.flapping.interval_sec == 60
    assert "ipv4" in cfg.flapping.address_families


def test_init_no_overwrite(tmp_path):
    output = tmp_path / "config.yaml"
    output.write_text("original content")
    runner = CliRunner()
    inp = _build_input("N")  # decline overwrite
    result = runner.invoke(cli, ["init", str(output)], input=inp)
    assert result.exit_code != 0
    assert output.read_text() == "original content"


def test_init_force_overwrite(tmp_path):
    output = tmp_path / "config.yaml"
    output.write_text("original content")
    runner = CliRunner()
    inp = _build_input(
        65001, "10.0.0.2", "", "10.0.0.1", 65000,
        "Y", "N", "N", "N",
        100, "N",
    )
    result = runner.invoke(cli, ["init", "--force", str(output)], input=inp)
    assert result.exit_code == 0, result.output
    assert output.read_text() != "original content"

    data = yaml.safe_load(output.read_text())
    RouteToolConfig(**data)


def test_init_custom_output_path(tmp_path):
    output = tmp_path / "subdir" / "my-config.yaml"
    output.parent.mkdir()
    runner = CliRunner()
    inp = _build_input(
        65001, "10.0.0.2", "", "10.0.0.1", 65000,
        "Y", "N", "N", "N",
        100, "N",
    )
    result = runner.invoke(cli, ["init", str(output)], input=inp)
    assert result.exit_code == 0, result.output
    assert output.exists()

    data = yaml.safe_load(output.read_text())
    RouteToolConfig(**data)


def test_init_invalid_ip_retry(tmp_path):
    output = tmp_path / "config.yaml"
    runner = CliRunner()
    inp = _build_input(
        65001,
        "not-an-ip",   # invalid router_id
        "10.0.0.2",    # valid router_id on retry
        "",            # local_address default
        "10.0.0.1",
        65000,
        "Y", "N", "N", "N",
        100, "N",
    )
    result = runner.invoke(cli, ["init", str(output)], input=inp)
    assert result.exit_code == 0, result.output
    assert "Invalid IP address" in result.output

    data = yaml.safe_load(output.read_text())
    cfg = RouteToolConfig(**data)
    assert cfg.bgp.router_id == "10.0.0.2"


def test_init_no_afi_selected(tmp_path):
    output = tmp_path / "config.yaml"
    runner = CliRunner()
    inp = _build_input(
        65001, "10.0.0.2", "", "10.0.0.1", 65000,
        "N", "N", "N", "N",  # decline all
        100,  # ipv4 count (force-enabled)
        "N",
    )
    result = runner.invoke(cli, ["init", str(output)], input=inp)
    assert result.exit_code == 0, result.output
    assert "enabling IPv4 by default" in result.output

    data = yaml.safe_load(output.read_text())
    cfg = RouteToolConfig(**data)
    assert cfg.routes.ipv4.enabled is True
