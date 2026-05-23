import pytest

from MCP_Server.units import db_from_live, db_to_live, pan_from_live, pan_to_live


def test_pan_center():
    assert pan_to_live(0) == 0.0


def test_pan_full_right():
    assert pan_to_live(100) == 1.0


def test_pan_full_left():
    assert pan_to_live(-100) == -1.0


def test_pan_clamps_out_of_range():
    assert pan_to_live(150) == 1.0
    assert pan_to_live(-150) == -1.0


def test_pan_roundtrip():
    for p in (-100, -50, 0, 25, 100):
        assert pan_from_live(pan_to_live(p)) == pytest.approx(p)


def test_db_zero_maps_to_unity_anchor():
    assert db_to_live(0.0) == pytest.approx(0.85, abs=1e-6)


def test_db_max_is_one():
    assert db_to_live(6.0) == 1.0
    assert db_to_live(99.0) == 1.0


def test_db_floor_is_zero():
    assert db_to_live(-70.0) == 0.0
    assert db_to_live(-120.0) == 0.0


def test_db_monotonic_increasing():
    vals = [db_to_live(d) for d in range(-60, 7)]
    assert vals == sorted(vals)


def test_db_roundtrip_midrange():
    for d in (-50, -25, -10, -6, 0, 6):
        assert db_from_live(db_to_live(d)) == pytest.approx(d, abs=1e-6)


def test_db_from_live_floor_is_neg_inf():
    assert db_from_live(0.0) == float("-inf")
