"""Human-unit <-> Ableton-internal conversions for mixer parameters.

Device parameters (EQ freq, comp ratio, synth cutoff...) are already in native
units and need no conversion here -- they are only clamped on the Remote Script
side. The conversions below cover the mixer fader and pan, whose Live-internal
values are NOT human units:

  - pan:            human -100..100 (L..R)  <->  Live -1.0..1.0
  - volume / sends: human dB              <->  Live's non-linear 0.0..1.0 fader

VOLUME CURVE IS APPROXIMATE. Live's fader maps 0.0..1.0 to roughly -inf..+6 dB
along a curve with no public closed form. We piecewise-linear-interpolate a
calibration table. The default anchors are community approximations; Task 7
refines them against a real Live set. The load-bearing anchors are 0 dB ~= 0.85
and +6 dB = 1.0.
"""

# (live_value, dB) anchors, ascending. Refine in Task 7.
_VOLUME_ANCHORS = [
    (0.0, -70.0),
    (0.2, -50.0),
    (0.4, -25.0),
    (0.6, -10.0),
    (0.7, -6.0),
    (0.85, 0.0),
    (1.0, 6.0),
]

DB_FLOOR = -70.0  # at/below this dB the fader is set to 0.0


def pan_to_live(pan):
    """Human pan -100..100 -> Live -1.0..1.0 (clamped)."""
    v = pan / 100.0
    return max(-1.0, min(1.0, v))


def pan_from_live(value):
    """Live -1.0..1.0 -> human -100..100."""
    return value * 100.0


def db_to_live(db):
    """Human dB -> Live fader value 0.0..1.0 (piecewise-linear, monotonic)."""
    if db <= DB_FLOOR:
        return 0.0
    if db >= _VOLUME_ANCHORS[-1][1]:
        return _VOLUME_ANCHORS[-1][0]
    for (v0, d0), (v1, d1) in zip(_VOLUME_ANCHORS, _VOLUME_ANCHORS[1:]):
        if d0 <= db <= d1:
            if d1 == d0:
                return v0
            frac = (db - d0) / (d1 - d0)
            return v0 + frac * (v1 - v0)
    return _VOLUME_ANCHORS[-1][0]


def db_from_live(value):
    """Live fader value 0.0..1.0 -> human dB (inverse of db_to_live)."""
    if value <= _VOLUME_ANCHORS[0][0]:
        return float("-inf")
    if value >= _VOLUME_ANCHORS[-1][0]:
        return _VOLUME_ANCHORS[-1][1]
    for (v0, d0), (v1, d1) in zip(_VOLUME_ANCHORS, _VOLUME_ANCHORS[1:]):
        if v0 <= value <= v1:
            if v1 == v0:
                return d0
            frac = (value - v0) / (v1 - v0)
            return d0 + frac * (d1 - d0)
    return _VOLUME_ANCHORS[-1][1]
