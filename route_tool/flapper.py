"""Route flapping engine with random, sequential, and burst patterns."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable

from route_tool.config import FlapPattern, FlappingConfig
from route_tool.generator import Route

log = logging.getLogger(__name__)


class Flapper:
    """Manages route flapping across address families."""

    def __init__(
        self,
        config: FlappingConfig,
        routes_by_afi: dict[str, list[Route]],
        announce_fn: Callable[[Route], None],
        withdraw_fn: Callable[[Route], None],
    ):
        self.config = config
        self.announce = announce_fn
        self.withdraw = withdraw_fn
        self._seq_offset: dict[str, int] = {}

        self.flap_routes: dict[str, list[Route]] = {}
        for afi in config.address_families:
            afi_routes = routes_by_afi.get(afi, [])
            if afi_routes:
                self.flap_routes[afi] = afi_routes
                self._seq_offset[afi] = 0

    def run(self, stop_event=None):
        """Run the flap loop. Blocks until duration expires or stop_event is set."""
        self._stop_event = stop_event

        if not self.flap_routes:
            log.warning("No routes available for flapping")
            return

        log.info(
            "Starting flap loop: pattern=%s interval=%ds percentage=%d%%",
            self.config.pattern.value,
            self.config.interval_sec,
            self.config.percentage,
        )

        if self.config.initial_delay_sec > 0:
            log.info("Waiting %ds for routes to stabilize...", self.config.initial_delay_sec)
            if self._interruptible_sleep(self.config.initial_delay_sec):
                return

        start = time.monotonic()
        cycle = 0

        while True:
            if stop_event and stop_event.is_set():
                break
            if self.config.duration_sec > 0:
                elapsed = time.monotonic() - start
                if elapsed >= self.config.duration_sec:
                    log.info("Flap duration reached (%ds)", self.config.duration_sec)
                    break

            cycle += 1
            if self._flap_cycle(cycle):
                break

            if self._interruptible_sleep(self.config.interval_sec):
                break

        log.info("Flap loop ended after %d cycles", cycle)

    def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep for the given duration, returning True if interrupted by stop_event."""
        if self._stop_event:
            return self._stop_event.wait(seconds)
        time.sleep(seconds)
        return False

    def _flap_cycle(self, cycle: int) -> bool:
        """Execute one flap cycle: withdraw then re-announce. Returns True if interrupted."""
        for afi, routes in self.flap_routes.items():
            selected = self._select_routes(afi, routes)
            if not selected:
                continue

            log.info(
                "Cycle %d: flapping %d %s routes (withdraw)",
                cycle, len(selected), afi,
            )
            for route in selected:
                self.withdraw(route)

        half_interval = self.config.interval_sec / 2
        if self._interruptible_sleep(half_interval):
            return True

        for afi, routes in self.flap_routes.items():
            selected = self._select_routes(afi, routes)
            if not selected:
                continue

            log.info(
                "Cycle %d: flapping %d %s routes (re-announce)",
                cycle, len(selected), afi,
            )
            for route in selected:
                self.announce(route)

        return False

    def _select_routes(self, afi: str, routes: list[Route]) -> list[Route]:
        """Select routes to flap based on the configured pattern."""
        if self.config.pattern == FlapPattern.RANDOM:
            return self._select_random(routes)
        elif self.config.pattern == FlapPattern.SEQUENTIAL:
            return self._select_sequential(afi, routes)
        elif self.config.pattern == FlapPattern.BURST:
            return self._select_burst(routes)
        return []

    def _select_random(self, routes: list[Route]) -> list[Route]:
        count = max(1, len(routes) * self.config.percentage // 100)
        return random.sample(routes, min(count, len(routes)))

    def _select_sequential(self, afi: str, routes: list[Route]) -> list[Route]:
        count = max(1, len(routes) * self.config.percentage // 100)
        offset = self._seq_offset.get(afi, 0)
        selected = []
        for i in range(count):
            idx = (offset + i) % len(routes)
            selected.append(routes[idx])
        self._seq_offset[afi] = (offset + count) % len(routes)
        return selected

    def _select_burst(self, routes: list[Route]) -> list[Route]:
        count = min(self.config.burst_size, len(routes))
        return random.sample(routes, count)
