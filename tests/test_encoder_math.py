"""Unit tests for the pure bitrate/size math (no Qt required)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discordvidshare.encoder import (  # noqa: E402
    DEFAULT_SAFETY,
    compute_video_bitrate_bps,
    estimate_output_bytes,
)
from discordvidshare.media_info import (  # noqa: E402
    format_timecode,
    parse_timecode,
)


def test_bitrate_round_trips_to_target_size():
    # 30-second clip, 10 MB target, 128 kbps audio.
    duration = 30.0
    target = 10 * 1_000_000
    audio = 128_000
    vb = compute_video_bitrate_bps(target, duration, audio)
    est = estimate_output_bytes(vb, duration, audio)
    # Predicted size should land within the safety margin, never over target.
    assert est <= target
    assert est >= target * (DEFAULT_SAFETY - 0.02)


def test_bitrate_scales_with_duration():
    target = 25 * 1_000_000
    short = compute_video_bitrate_bps(target, 10.0)
    long = compute_video_bitrate_bps(target, 60.0)
    assert short > long  # longer clip => lower bitrate for the same size


def test_audio_budget_is_subtracted():
    target = 10 * 1_000_000
    duration = 20.0
    with_audio = compute_video_bitrate_bps(target, duration, 192_000)
    without_audio = compute_video_bitrate_bps(target, duration, 0)
    assert without_audio > with_audio


def test_zero_duration_is_safe():
    assert compute_video_bitrate_bps(1_000_000, 0.0) == 0


def test_timecode_round_trip():
    assert parse_timecode("00:00:05.000") == 5.0
    assert parse_timecode("1:30") == 90.0
    assert parse_timecode("2:00:00") == 7200.0
    assert parse_timecode("bad") is None
    assert format_timecode(5.0) == "00:00:05.000"
    assert format_timecode(90.0, show_ms=False) == "00:01:30"


if __name__ == "__main__":
    import traceback

    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS {name}")
            except Exception:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
