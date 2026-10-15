"""Tests for docflow_agent.stability — file stability checking."""

import os
import pathlib
from typing import Any
import pytest

from docflow_agent.stability import StabilityResult, check_stability


class FakeClock:
    """Mock clock and sleep provider for instant, deterministic tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.current_time = start

    def time(self) -> float:
        return self.current_time

    def sleep(self, seconds: float) -> None:
        self.current_time += seconds


class TestStabilityChecking:
    """Test stability evaluation, growing files, locked files, and timeouts."""

    def test_file_becomes_stable_after_required_samples(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "test.pdf"
        p.write_bytes(b"%PDF-1.4 sample content %%EOF")

        clock = FakeClock()
        res = check_stability(
            p,
            sample_interval_seconds=2.0,
            required_samples=3,
            timeout_seconds=120.0,
            time_fn=clock.time,
            sleep_fn=clock.sleep,
        )

        assert res.is_stable is True
        assert res.samples_collected == 3
        assert res.file_size_bytes == len(b"%PDF-1.4 sample content %%EOF")
        assert res.mtime_ns > 0
        assert res.reason_code is None
        # 3 samples taken at t=0s, t=2s, t=4s
        assert clock.current_time == 4.0

    def test_growing_file_resets_sample_count(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "growing.pdf"
        p.write_bytes(b"initial chunk")

        clock = FakeClock()
        original_sleep = clock.sleep

        def growing_sleep(seconds: float) -> None:
            original_sleep(seconds)
            # After 1st sleep (at t=2s), append data to simulate LIS writing
            if clock.current_time == 2.0:
                with open(p, "ab") as f:
                    f.write(b" second chunk")
                # Ensure mtime changes
                os.utime(p, (clock.current_time, clock.current_time))

        res = check_stability(
            p,
            sample_interval_seconds=2.0,
            required_samples=3,
            timeout_seconds=30.0,
            time_fn=clock.time,
            sleep_fn=growing_sleep,
        )

        assert res.is_stable is True
        # File grew at t=2s, baseline reset at t=2s, stable after 3 consecutive samples (t=2s, t=4s, t=6s)
        assert res.samples_collected == 3
        assert res.file_size_bytes == len(b"initial chunk second chunk")

    def test_locked_file_resets_sample_count(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        p = tmp_path / "locked.pdf"
        p.write_bytes(b"sample bytes")

        clock = FakeClock()
        attempts = 0

        # Simulate PermissionError on open for the first 2 calls
        original_open = open

        def mock_open(file: str | bytes | os.PathLike[Any], mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise PermissionError("WinError 32: The process cannot access the file")
            return original_open(file, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", mock_open)

        res = check_stability(
            p,
            sample_interval_seconds=2.0,
            required_samples=3,
            timeout_seconds=30.0,
            time_fn=clock.time,
            sleep_fn=clock.sleep,
        )

        assert res.is_stable is True
        assert res.samples_collected == 3
        assert res.file_size_bytes == len(b"sample bytes")

    def test_disappearing_file_resets_count_and_times_out(self, tmp_path: pathlib.Path) -> None:
        p = tmp_path / "vanish.pdf"
        p.write_bytes(b"temp")

        clock = FakeClock()
        original_sleep = clock.sleep

        def deleting_sleep(seconds: float) -> None:
            original_sleep(seconds)
            # Delete file after 1st sample
            if p.exists():
                p.unlink()

        res = check_stability(
            p,
            sample_interval_seconds=2.0,
            required_samples=3,
            timeout_seconds=10.0,
            time_fn=clock.time,
            sleep_fn=deleting_sleep,
        )

        assert res.is_stable is False
        assert res.reason_code == "stability_timeout_after_policy"

    def test_stability_timeout_returns_retryable_outcome_without_quarantining(
        self, tmp_path: pathlib.Path,
    ) -> None:
        p = tmp_path / "always_growing.pdf"
        p.write_bytes(b"init")

        clock = FakeClock()

        # Simulate continuously growing file on every sample
        def always_growing_sleep(seconds: float) -> None:
            clock.sleep(seconds)
            with open(p, "ab") as f:
                f.write(b"x")
            os.utime(p, (clock.current_time, clock.current_time))

        res = check_stability(
            p,
            sample_interval_seconds=2.0,
            required_samples=3,
            timeout_seconds=10.0,
            time_fn=clock.time,
            sleep_fn=always_growing_sleep,
        )

        assert res.is_stable is False
        assert res.reason_code == "stability_timeout_after_policy"
        # File still exists in place and must not be deleted or quarantined
        assert p.exists()
