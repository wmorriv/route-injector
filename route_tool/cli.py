"""CLI for route-tool — manages ExaBGP container for BGP route injection."""

from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
from pathlib import Path

import click

from route_tool.config import RouteToolConfig, load_config
from route_tool.generator import generate_all_routes

CONTAINER_NAME = "route-tool"
IMAGE_NAME = "route-tool:latest"


@click.group()
@click.version_option(package_name="route-tool")
def cli():
    """ExaBGP route injection tool for BGP scale testing."""


@cli.command()
@click.option("-c", "--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--peer-address", default=None, help="Override BGP peer address")
@click.option("--local-as", default=None, type=int, help="Override local AS number")
@click.option("--count", default=None, type=int, help="Override route count for all enabled AFIs")
@click.option("--flap-interval", default=None, type=int, help="Override flap interval (seconds)")
@click.option("--flap-percentage", default=None, type=int, help="Override flap percentage")
@click.option("--no-flap", is_flag=True, default=False, help="Disable route flapping")
@click.option("--build/--no-build", default=True, help="Build Docker image before running")
@click.option("--detach/--no-detach", default=True, help="Run container in background")
def run(config_path, peer_address, local_as, count, flap_interval, flap_percentage, no_flap, build, detach):
    """Start ExaBGP container with route injection."""
    overrides = {}
    if peer_address:
        overrides["peer_address"] = peer_address
    if local_as:
        overrides["local_as"] = local_as
    if count:
        overrides["count"] = count
    if flap_interval:
        overrides["flap_interval"] = flap_interval
    if flap_percentage:
        overrides["flap_percentage"] = flap_percentage
    if no_flap:
        overrides["no_flap"] = True

    try:
        cfg = load_config(config_path, overrides if overrides else None)
    except Exception as e:
        click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    total = sum(
        getattr(cfg.routes, afi).count
        for afi in ("ipv4", "ipv6", "vpnv4", "vpnv6")
        if getattr(cfg.routes, afi).enabled
    )
    click.echo(f"Config validated. Peer: {cfg.bgp.peer_address}, Total routes: {total}")

    if build:
        click.echo("Building Docker image...")
        project_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["docker", "build", "-t", IMAGE_NAME, str(project_root)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            click.echo(f"Docker build failed:\n{result.stderr}", err=True)
            sys.exit(1)
        click.echo("Image built successfully")

    _stop_existing()

    abs_config = str(config_path.resolve())
    docker_cmd = [
        "docker", "run",
        "--name", CONTAINER_NAME,
        "--network", "host",
        "-v", f"{abs_config}:/config/config.yaml:ro",
    ]

    if overrides:
        env_overrides = []
        if peer_address:
            env_overrides.append(f"OVERRIDE_PEER_ADDRESS={peer_address}")
        if local_as:
            env_overrides.append(f"OVERRIDE_LOCAL_AS={local_as}")
        if count:
            env_overrides.append(f"OVERRIDE_COUNT={count}")
        if no_flap:
            env_overrides.append("OVERRIDE_NO_FLAP=1")
        if flap_interval:
            env_overrides.append(f"OVERRIDE_FLAP_INTERVAL={flap_interval}")
        if flap_percentage:
            env_overrides.append(f"OVERRIDE_FLAP_PERCENTAGE={flap_percentage}")
        for env in env_overrides:
            docker_cmd.extend(["-e", env])

    if detach:
        docker_cmd.append("-d")

    docker_cmd.append(IMAGE_NAME)

    click.echo(f"Starting container '{CONTAINER_NAME}'...")
    result = subprocess.run(docker_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        click.echo(f"Failed to start container:\n{result.stderr}", err=True)
        sys.exit(1)

    if detach:
        click.echo(f"Container started. View logs: route-tool logs")
    else:
        click.echo(result.stdout)


@cli.command()
def stop():
    """Stop and remove the route-tool container."""
    _stop_existing()
    click.echo("Container stopped")


@cli.command()
@click.option("-c", "--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
def validate(config_path):
    """Validate a config file without starting anything."""
    try:
        cfg = load_config(config_path)
    except Exception as e:
        click.echo(f"Validation FAILED: {e}", err=True)
        sys.exit(1)

    enabled = [
        afi for afi in ("ipv4", "ipv6", "vpnv4", "vpnv6")
        if getattr(cfg.routes, afi).enabled
    ]
    total = sum(getattr(cfg.routes, afi).count for afi in enabled)

    click.echo("Config is valid")
    click.echo(f"  Peer: {cfg.bgp.peer_address} (AS {cfg.bgp.peer_as})")
    click.echo(f"  Local: {cfg.bgp.local_address} (AS {cfg.bgp.local_as})")
    click.echo(f"  Address families: {', '.join(enabled)}")
    click.echo(f"  Total routes: {total}")
    if cfg.flapping.enabled:
        click.echo(
            f"  Flapping: {cfg.flapping.pattern.value} pattern, "
            f"{cfg.flapping.percentage}% every {cfg.flapping.interval_sec}s"
        )
    else:
        click.echo("  Flapping: disabled")


@cli.command()
@click.option("-c", "--config", "config_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("-n", "--sample", default=5, type=int, help="Number of sample routes per AFI")
def preview(config_path, sample):
    """Preview routes that would be generated (dry run)."""
    try:
        cfg = load_config(config_path)
    except Exception as e:
        click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    all_routes = generate_all_routes(cfg.routes)

    for afi, routes in all_routes.items():
        click.echo(f"\n--- {afi.upper()} ({len(routes)} routes) ---")
        show = routes[:sample]
        for route in show:
            click.echo(f"  {route.to_announce()}")
        if len(routes) > sample:
            click.echo(f"  ... and {len(routes) - sample} more")


@cli.command()
def status():
    """Show container and BGP neighbor status."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f",
             "{{.State.Status}}|{{.State.StartedAt}}",
             CONTAINER_NAME],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        click.echo("Docker is not installed or not in PATH", err=True)
        sys.exit(1)

    if result.returncode != 0:
        click.echo("Container is not running")
        return

    parts = result.stdout.strip().split("|")
    container_status = parts[0]
    started_at = parts[1] if len(parts) > 1 else "unknown"

    click.echo(f"Container: {container_status} (started {started_at})")

    if container_status != "running":
        click.echo("Container is not running — start it with: route-tool run -c <config>")
        return

    click.echo("")
    click.echo("--- BGP Neighbor ---")
    neighbor_output = _exabgpcli("show", "neighbor", "summary")
    if neighbor_output:
        click.echo(neighbor_output)
    else:
        click.echo("  (exabgpcli unavailable, falling back to logs)")
        _status_from_logs()

    click.echo("")
    click.echo("--- Route Counts ---")
    adj_output = _exabgpcli("show", "adj-rib", "out")
    if adj_output:
        lines = adj_output.splitlines()
        click.echo(f"  Adj-RIB-Out entries: {len(lines)}")
    else:
        _route_counts_from_logs()

    click.echo("")
    click.echo("--- Controller Status ---")
    _controller_status_from_logs()


def _exabgpcli(*args: str) -> str | None:
    """Run an exabgpcli command inside the container. Returns output or None on failure."""
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME,
             "env", "exabgp.api.pipename=/run/exabgp/exabgp",
             "exabgpcli", *args],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _status_from_logs():
    """Parse recent logs for peer state info."""
    result = subprocess.run(
        ["docker", "logs", "--tail", "50", CONTAINER_NAME],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    peer_state = "unknown"
    for line in reversed(output.splitlines()):
        lower = line.lower()
        if "peer connected" in lower or "connected" in lower and "neighbor" in lower:
            peer_state = "established"
            break
        elif "tcp connection failed" in lower or "connection refused" in lower:
            peer_state = "connect-fail"
            break
        elif "peer reset" in lower or "notification" in lower:
            peer_state = "down"
            break
    click.echo(f"  Peer state (from logs): {peer_state}")


def _route_counts_from_logs():
    """Parse logs for route announcement counts."""
    result = subprocess.run(
        ["docker", "logs", "--tail", "200", CONTAINER_NAME],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    announced = {}
    total_announced = 0
    for line in output.splitlines():
        if "Generated" in line and "routes" in line:
            for afi in ("IPv4 unicast", "IPv6 unicast", "VPNv4", "VPNv6"):
                if afi in line:
                    try:
                        count = int(line.split("Generated")[1].split()[0])
                        announced[afi] = count
                    except (ValueError, IndexError):
                        pass
        if "All" in line and "routes announced" in line:
            try:
                total_announced = int(line.split("All")[1].split()[0])
            except (ValueError, IndexError):
                pass

    if announced:
        for afi, count in announced.items():
            click.echo(f"  {afi}: {count}")
        if total_announced:
            click.echo(f"  Total announced: {total_announced}")
    else:
        click.echo("  No route counts found in logs yet")


def _controller_status_from_logs():
    """Determine controller state from recent logs."""
    result = subprocess.run(
        ["docker", "logs", "--tail", "30", CONTAINER_NAME],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    lines = output.splitlines()

    state = "initializing"
    for line in reversed(lines):
        lower = line.lower()
        if "flap loop ended" in lower or "controller shutting down" in lower:
            state = "stopped"
            break
        elif "starting flap loop" in lower or "flapping" in lower:
            state = "flapping"
            break
        elif "all" in lower and "routes announced" in lower:
            state = "routes announced, holding"
            break
        elif "waiting" in lower and "stabilize" in lower:
            state = "waiting for stabilization"
            break
        elif "announcing" in lower:
            state = "announcing routes"
            break
        elif "waiting for bgp peer" in lower:
            state = "waiting for peer"
            break

    click.echo(f"  Controller: {state}")


@cli.command()
@click.option("-f", "--follow", is_flag=True, default=True, help="Follow log output")
@click.option("-n", "--tail", default=100, type=int, help="Number of lines to show")
def logs(follow, tail):
    """View container logs."""
    cmd = ["docker", "logs"]
    if follow:
        cmd.append("-f")
    cmd.extend(["--tail", str(tail), CONTAINER_NAME])

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


def _prompt_ip(text: str, default: str | None = None) -> str:
    while True:
        value = click.prompt(text, default=default) if default else click.prompt(text)
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            click.echo(f"  Invalid IP address: {value}", err=True)


def _render_config_yaml(data: dict) -> str:
    lines = [
        "# Route-Tool Configuration",
        "# Generated by: route-tool init",
        "",
    ]

    bgp = data["bgp"]
    lines.append("bgp:")
    lines.append(f"  local_as: {bgp['local_as']}")
    lines.append(f"  peer_address: {bgp['peer_address']}        # BGP peer / DUT address")
    lines.append(f"  peer_as: {bgp['peer_as']}")
    lines.append(f"  router_id: {bgp['router_id']}")
    lines.append(f"  local_address: {bgp['local_address']}       # Source address for BGP session")
    lines.append(f"  hold_time: {bgp['hold_time']}")
    lines.append("")

    routes = data.get("routes", {})
    lines.append("routes:")

    # IPv4
    lines.append("  # IPv4 Unicast")
    lines.append("  ipv4:")
    ipv4 = routes.get("ipv4", {})
    lines.append(f"    enabled: {str(ipv4.get('enabled', False)).lower()}")
    lines.append(f"    count: {ipv4.get('count', 100)}")
    lines.append(f'    base_prefix: "{ipv4.get("base_prefix", "198.51.100.0/24")}"')
    lines.append(f"    prefix_length: {ipv4.get('prefix_length', 32)}")
    lines.append(f'    next_hop: "{ipv4.get("next_hop", "10.0.0.2")}"')
    lines.append("    # communities: [\"65001:100\"]")
    lines.append("    # med: 100")
    lines.append("    # as_path: [65001, 65002]")
    lines.append("")

    # IPv6
    lines.append("  # IPv6 Unicast")
    lines.append("  ipv6:")
    ipv6 = routes.get("ipv6", {})
    lines.append(f"    enabled: {str(ipv6.get('enabled', False)).lower()}")
    lines.append(f"    count: {ipv6.get('count', 100)}")
    lines.append(f'    base_prefix: "{ipv6.get("base_prefix", "2001:db8::/32")}"')
    lines.append(f"    prefix_length: {ipv6.get('prefix_length', 48)}")
    lines.append(f'    next_hop: "{ipv6.get("next_hop", "2001:db8::2")}"')
    lines.append("")

    # VPNv4
    lines.append("  # VPNv4 (IPv4 MPLS VPN)")
    lines.append("  vpnv4:")
    vpnv4 = routes.get("vpnv4", {})
    lines.append(f"    enabled: {str(vpnv4.get('enabled', False)).lower()}")
    lines.append(f"    count: {vpnv4.get('count', 100)}")
    lines.append(f'    base_prefix: "{vpnv4.get("base_prefix", "10.0.0.0/8")}"')
    lines.append(f"    prefix_length: {vpnv4.get('prefix_length', 24)}")
    lines.append(f'    next_hop: "{vpnv4.get("next_hop", "10.0.0.2")}"')
    lines.append(f'    rd: "{vpnv4.get("rd", "65001:1")}"')
    lines.append("    route_targets:")
    for rt in vpnv4.get("route_targets", ["65001:100"]):
        lines.append(f'      - "{rt}"')
    lines.append("")

    # VPNv6
    lines.append("  # VPNv6 (IPv6 MPLS VPN)")
    lines.append("  vpnv6:")
    vpnv6 = routes.get("vpnv6", {})
    lines.append(f"    enabled: {str(vpnv6.get('enabled', False)).lower()}")
    lines.append(f"    count: {vpnv6.get('count', 100)}")
    lines.append(f'    base_prefix: "{vpnv6.get("base_prefix", "fd00::/16")}"')
    lines.append(f"    prefix_length: {vpnv6.get('prefix_length', 48)}")
    lines.append(f'    next_hop: "{vpnv6.get("next_hop", "::ffff:10.0.0.2")}"')
    lines.append(f'    rd: "{vpnv6.get("rd", "65001:2")}"')
    lines.append("    route_targets:")
    for rt in vpnv6.get("route_targets", ["65001:200"]):
        lines.append(f'      - "{rt}"')
    lines.append("")

    # Flapping
    flap = data.get("flapping", {})
    lines.append("# Route Flapping Configuration")
    lines.append("flapping:")
    lines.append(f"  enabled: {str(flap.get('enabled', False)).lower()}")
    lines.append(f"  percentage: {flap.get('percentage', 10)}")
    lines.append(f"  interval_sec: {flap.get('interval_sec', 30)}")
    lines.append(f"  pattern: {flap.get('pattern', 'random')}")
    lines.append("  address_families:")
    for afi in flap.get("address_families", ["ipv4"]):
        lines.append(f"    - {afi}")
    lines.append(f"  duration_sec: {flap.get('duration_sec', 0)}")
    lines.append(f"  burst_size: {flap.get('burst_size', 50)}")
    lines.append(f"  initial_delay_sec: {flap.get('initial_delay_sec', 60)}")
    lines.append("")

    return "\n".join(lines)


@cli.command()
@click.argument("output", default="config.yaml", type=click.Path(path_type=Path))
@click.option("--force", is_flag=True, default=False, help="Overwrite existing file without confirmation")
def init(output: Path, force: bool):
    """Interactively generate a route-tool config file."""
    if output.exists() and not force:
        click.confirm(f"{output} already exists. Overwrite?", abort=True)

    click.echo("--- BGP Session ---")
    local_as = click.prompt("Local AS number", type=click.IntRange(1, 4294967295))
    router_id = _prompt_ip("Router ID (IPv4 address)")
    local_address = _prompt_ip("Local address (BGP source)", default=router_id)
    peer_address = _prompt_ip("Peer address (DUT)")
    peer_as = click.prompt("Peer AS number", type=click.IntRange(1, 4294967295))

    click.echo("")
    click.echo("--- Address Families ---")
    enable_ipv4 = click.confirm("Enable IPv4 unicast?", default=True)
    enable_ipv6 = click.confirm("Enable IPv6 unicast?", default=False)
    enable_vpnv4 = click.confirm("Enable VPNv4?", default=False)
    enable_vpnv6 = click.confirm("Enable VPNv6?", default=False)

    if not any([enable_ipv4, enable_ipv6, enable_vpnv4, enable_vpnv6]):
        click.echo("Warning: No address families selected, enabling IPv4 by default.")
        enable_ipv4 = True

    enabled_afis = []
    routes_data = {}

    click.echo("")
    click.echo("--- Route Counts ---")
    for afi, enabled in [("ipv4", enable_ipv4), ("ipv6", enable_ipv6),
                         ("vpnv4", enable_vpnv4), ("vpnv6", enable_vpnv6)]:
        if enabled:
            count = click.prompt(
                f"  {afi.upper()} route count",
                type=click.IntRange(1, 1_000_000),
                default=100,
            )
            routes_data[afi] = {"enabled": True, "count": count}
            enabled_afis.append(afi)
        else:
            routes_data[afi] = {"enabled": False}

    click.echo("")
    flap_data = {"enabled": False}
    enable_flapping = click.confirm("Enable route flapping?", default=False)
    if enable_flapping:
        flap_percentage = click.prompt("  Flap percentage (1-100)", type=click.IntRange(1, 100), default=10)
        flap_interval = click.prompt("  Flap interval (seconds)", type=click.IntRange(1), default=30)
        flap_data = {
            "enabled": True,
            "percentage": flap_percentage,
            "interval_sec": flap_interval,
            "pattern": "random",
            "address_families": enabled_afis,
            "duration_sec": 0,
            "burst_size": 50,
            "initial_delay_sec": 60,
        }

    config_data = {
        "bgp": {
            "local_as": local_as,
            "peer_address": peer_address,
            "peer_as": peer_as,
            "router_id": router_id,
            "local_address": local_address,
            "hold_time": 90,
        },
        "routes": routes_data,
        "flapping": flap_data,
    }

    try:
        RouteToolConfig(**config_data)
    except Exception as e:
        click.echo(f"Validation error: {e}", err=True)
        sys.exit(1)

    yaml_content = _render_config_yaml(config_data)
    output.write_text(yaml_content)

    click.echo("")
    click.echo(f"Config written to {output}")
    click.echo(f"  Validate: route-tool validate -c {output}")
    click.echo(f"  Run:      route-tool run -c {output}")


def _stop_existing():
    """Stop and remove existing container if running."""
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True, text=True,
    )


def main():
    cli()


if __name__ == "__main__":
    main()
