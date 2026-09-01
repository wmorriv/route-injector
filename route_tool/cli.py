"""CLI for route-tool — manages ExaBGP container for BGP route injection."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

from route_tool.config import load_config
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
