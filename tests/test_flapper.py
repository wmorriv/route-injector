"""Tests for the route flapping engine."""

import threading

import pytest

from route_tool.config import FlapPattern, FlappingConfig
from route_tool.generator import Route


def _make_routes(count: int, afi: str = "ipv4") -> list[Route]:
    return [
        Route(
            prefix=f"198.51.100.{i}",
            prefix_length=32,
            next_hop="10.0.0.2",
            afi=afi,
        )
        for i in range(count)
    ]


def test_random_selection():
    from route_tool.flapper import Flapper

    routes = _make_routes(100)
    withdrawn = []
    announced = []

    cfg = FlappingConfig(
        enabled=True,
        percentage=10,
        pattern=FlapPattern.RANDOM,
        address_families=["ipv4"],
        interval_sec=1,
        initial_delay_sec=0,
        duration_sec=0,
    )
    flapper = Flapper(
        config=cfg,
        routes_by_afi={"ipv4": routes},
        announce_fn=lambda r: announced.append(r),
        withdraw_fn=lambda r: withdrawn.append(r),
    )
    selected = flapper._select_random(routes)
    assert len(selected) == 10
    assert all(r in routes for r in selected)


def test_sequential_selection_wraps():
    from route_tool.flapper import Flapper

    routes = _make_routes(10)
    cfg = FlappingConfig(
        enabled=True,
        percentage=30,
        pattern=FlapPattern.SEQUENTIAL,
        address_families=["ipv4"],
        interval_sec=1,
        initial_delay_sec=0,
    )
    flapper = Flapper(
        config=cfg,
        routes_by_afi={"ipv4": routes},
        announce_fn=lambda r: None,
        withdraw_fn=lambda r: None,
    )

    batch1 = flapper._select_sequential("ipv4", routes)
    assert len(batch1) == 3
    assert batch1[0].prefix == "198.51.100.0"

    batch2 = flapper._select_sequential("ipv4", routes)
    assert batch2[0].prefix == "198.51.100.3"

    batch3 = flapper._select_sequential("ipv4", routes)
    assert batch3[0].prefix == "198.51.100.6"

    batch4 = flapper._select_sequential("ipv4", routes)
    assert batch4[0].prefix == "198.51.100.9"
    assert batch4[1].prefix == "198.51.100.0"


def test_burst_selection():
    from route_tool.flapper import Flapper

    routes = _make_routes(100)
    cfg = FlappingConfig(
        enabled=True,
        pattern=FlapPattern.BURST,
        burst_size=25,
        address_families=["ipv4"],
        interval_sec=1,
        initial_delay_sec=0,
    )
    flapper = Flapper(
        config=cfg,
        routes_by_afi={"ipv4": routes},
        announce_fn=lambda r: None,
        withdraw_fn=lambda r: None,
    )
    selected = flapper._select_burst(routes)
    assert len(selected) == 25


def test_burst_capped_at_route_count():
    from route_tool.flapper import Flapper

    routes = _make_routes(10)
    cfg = FlappingConfig(
        enabled=True,
        pattern=FlapPattern.BURST,
        burst_size=100,
        address_families=["ipv4"],
        interval_sec=1,
        initial_delay_sec=0,
    )
    flapper = Flapper(
        config=cfg,
        routes_by_afi={"ipv4": routes},
        announce_fn=lambda r: None,
        withdraw_fn=lambda r: None,
    )
    selected = flapper._select_burst(routes)
    assert len(selected) == 10


def test_flap_duration_stops():
    from route_tool.flapper import Flapper

    routes = _make_routes(10)
    withdrawn = []
    announced = []

    cfg = FlappingConfig(
        enabled=True,
        percentage=50,
        pattern=FlapPattern.RANDOM,
        address_families=["ipv4"],
        interval_sec=1,
        initial_delay_sec=0,
        duration_sec=2,
    )
    flapper = Flapper(
        config=cfg,
        routes_by_afi={"ipv4": routes},
        announce_fn=lambda r: announced.append(r),
        withdraw_fn=lambda r: withdrawn.append(r),
    )
    flapper.run()
    assert len(withdrawn) > 0
    assert len(announced) > 0


def test_stop_event():
    from route_tool.flapper import Flapper

    routes = _make_routes(10)
    cfg = FlappingConfig(
        enabled=True,
        percentage=50,
        pattern=FlapPattern.RANDOM,
        address_families=["ipv4"],
        interval_sec=60,
        initial_delay_sec=0,
        duration_sec=0,
    )
    stop = threading.Event()
    flapper = Flapper(
        config=cfg,
        routes_by_afi={"ipv4": routes},
        announce_fn=lambda r: None,
        withdraw_fn=lambda r: None,
    )

    def run_flapper():
        flapper.run(stop_event=stop)

    t = threading.Thread(target=run_flapper)
    t.start()
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()


def test_no_routes_for_afi():
    from route_tool.flapper import Flapper

    cfg = FlappingConfig(
        enabled=True,
        address_families=["ipv6"],
        interval_sec=1,
        initial_delay_sec=0,
        duration_sec=1,
    )
    flapper = Flapper(
        config=cfg,
        routes_by_afi={"ipv4": _make_routes(10)},
        announce_fn=lambda r: None,
        withdraw_fn=lambda r: None,
    )
    flapper.run()
