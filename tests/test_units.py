"""Plain-assert tests for MCP_Server/units.py (no pytest dependency).
Run: python tests/test_units.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from MCP_Server.units import db_to_live, db_from_live, pan_to_live, pan_from_live


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_anchor_points():
    # Load-bearing anchors from the design: 0 dB ~= 0.85 fader, +6 dB = 1.0.
    assert approx(db_to_live(0.0), 0.85)
    assert approx(db_to_live(6.0), 1.0)


def test_floor_and_ceiling():
    assert db_to_live(-70.0) == 0.0
    assert db_to_live(-1000.0) == 0.0     # below floor clamps to 0
    assert db_to_live(99.0) == 1.0        # above ceiling clamps to 1


def test_volume_monotonic():
    prev = -1.0
    db = -70.0
    while db <= 6.0:
        v = db_to_live(db)
        assert v >= prev, "fader must be non-decreasing in dB"
        prev = v
        db += 0.5


def test_volume_round_trip():
    # db_from_live(db_to_live(x)) recovers x within a coarse interpolation tol.
    for db in (-50.0, -25.0, -10.0, -6.0, 0.0, 6.0):
        assert approx(db_from_live(db_to_live(db)), db, tol=0.5)


def test_pan():
    assert approx(pan_to_live(-100), -1.0)
    assert approx(pan_to_live(0), 0.0)
    assert approx(pan_to_live(100), 1.0)
    assert approx(pan_to_live(200), 1.0)      # clamps
    assert approx(pan_from_live(-1.0), -100.0)
    assert approx(pan_from_live(0.5), 50.0)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
