"""ExaBGP process controller — runs inside the container as ExaBGP's process.

Reads the YAML config, generates routes, announces them via stdout,
and optionally runs the flap loop.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path

from route_tool.config import load_config
from route_tool.flapper import Flapper
from route_tool.generator import Route, generate_all_routes

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("route-controller")

ANNOUNCE_BATCH_SIZE = 100
ANNOUNCE_BATCH_DELAY = 0.2


def _send(line: str) -> None:
    """Write a command to stdout for ExaBGP to process."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _announce_route(route: Route) -> None:
    _send(route.to_announce())


def _withdraw_route(route: Route) -> None:
    _send(route.to_withdraw())


def _wait_for_peer(timeout: int = 120) -> bool:
    """Wait for ExaBGP to report a peer connection on stdin."""
    log.info("Waiting for BGP peer connection (timeout %ds)...", timeout)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if sys.stdin in _select_stdin(1.0):
            line = sys.stdin.readline().strip()
            if not line:
                continue
            log.info("ExaBGP: %s", line)
            if "connected" in line.lower() or "up" in line.lower():
                log.info("Peer connected")
                return True

    log.warning("Timed out waiting for peer connection, announcing anyway")
    return False


def _select_stdin(timeout: float):
    """Non-blocking check for stdin readability."""
    import select
    readable, _, _ = select.select([sys.stdin], [], [], timeout)
    return readable


def _announce_routes(all_routes: dict[str, list[Route]]) -> None:
    """Announce all generated routes in batches."""
    total = sum(len(r) for r in all_routes.values())
    announced = 0

    for afi, routes in all_routes.items():
        log.info("Announcing %d %s routes...", len(routes), afi)
        for i, route in enumerate(routes):
            _announce_route(route)
            announced += 1
            if (i + 1) % ANNOUNCE_BATCH_SIZE == 0:
                time.sleep(ANNOUNCE_BATCH_DELAY)
                log.info("Progress: %d/%d routes announced", announced, total)

    log.info("All %d routes announced", total)


def main() -> None:
    if len(sys.argv) < 2:
        log.error("Usage: controller.py <config.yaml>")
        sys.exit(1)

    config_path = Path(sys.argv[1])
    log.info("Loading config from %s", config_path)
    cfg = load_config(config_path)

    stop_event = threading.Event()

    def handle_signal(signum, frame):
        log.info("Received signal %d, shutting down...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info("Generating routes...")
    all_routes = generate_all_routes(cfg.routes)

    if not all_routes:
        log.error("No address families enabled — nothing to announce")
        sys.exit(1)

    _wait_for_peer()

    _announce_routes(all_routes)

    if cfg.flapping.enabled:
        flapper = Flapper(
            config=cfg.flapping,
            routes_by_afi=all_routes,
            announce_fn=_announce_route,
            withdraw_fn=_withdraw_route,
        )
        flapper.run(stop_event=stop_event)
    else:
        log.info("Flapping disabled — holding routes. Send SIGTERM to exit.")
        stop_event.wait()

    log.info("Controller shutting down")


if __name__ == "__main__":
    main()
