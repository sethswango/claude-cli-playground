"""Unit tests for sysglance.py — GPU fallback, --once arg parsing, color thresholds."""

import subprocess
import sys
from unittest import mock

import pytest

import sysglance


# ---------------------------------------------------------------------------
# Color threshold logic (make_bar)
# ---------------------------------------------------------------------------

class TestMakeBarColorThresholds:
    """make_bar should pick green ≤60 %, yellow 61-85 %, red >85 %."""

    def test_low_usage_green(self):
        text = sysglance.make_bar("Test", 30.0)
        # default color should remain green (not overridden)
        spans = text._spans
        rendered = text.plain
        assert "30.0%" in rendered
        # No yellow or red override should have happened; color stays green
        style_strs = [str(s.style) for s in spans]
        assert any("green" in s for s in style_strs)
        assert not any("yellow" in s for s in style_strs)
        assert not any("red" in s for s in style_strs)

    def test_boundary_60_stays_green(self):
        text = sysglance.make_bar("CPU", 60.0)
        style_strs = [str(s.style) for s in text._spans]
        assert any("green" in s for s in style_strs)
        assert not any("yellow" in s for s in style_strs)

    def test_above_60_yellow(self):
        text = sysglance.make_bar("CPU", 61.0)
        style_strs = [str(s.style) for s in text._spans]
        assert any("yellow" in s for s in style_strs)

    def test_boundary_85_stays_yellow(self):
        text = sysglance.make_bar("MEM", 85.0)
        style_strs = [str(s.style) for s in text._spans]
        assert any("yellow" in s for s in style_strs)
        assert not any("red" in s for s in style_strs)

    def test_above_85_red(self):
        text = sysglance.make_bar("MEM", 86.0)
        style_strs = [str(s.style) for s in text._spans]
        assert any("red" in s for s in style_strs)

    def test_zero_percent_green(self):
        text = sysglance.make_bar("Idle", 0.0)
        style_strs = [str(s.style) for s in text._spans]
        assert any("green" in s for s in style_strs)

    def test_100_percent_red(self):
        text = sysglance.make_bar("Full", 100.0)
        style_strs = [str(s.style) for s in text._spans]
        assert any("red" in s for s in style_strs)

    def test_bar_label_present(self):
        text = sysglance.make_bar("Swap", 42.0)
        assert "Swap" in text.plain

    def test_custom_default_color_overridden_by_threshold(self):
        """Even if caller passes color='cyan', thresholds still override."""
        text = sysglance.make_bar("X", 90.0, color="cyan")
        style_strs = [str(s.style) for s in text._spans]
        assert any("red" in s for s in style_strs)


# ---------------------------------------------------------------------------
# --once flag argument parsing
# ---------------------------------------------------------------------------

class TestParseArgs:
    """parse_args should handle --once flag correctly."""

    def test_once_flag_present(self):
        with mock.patch("sys.argv", ["sysglance", "--once"]):
            args = sysglance.parse_args()
        assert args.once is True

    def test_once_flag_absent(self):
        with mock.patch("sys.argv", ["sysglance"]):
            args = sysglance.parse_args()
        assert args.once is False

    def test_unknown_flag_errors(self):
        with mock.patch("sys.argv", ["sysglance", "--bogus"]):
            with pytest.raises(SystemExit):
                sysglance.parse_args()


# ---------------------------------------------------------------------------
# GPU detection fallback (gpu_panel)
# ---------------------------------------------------------------------------

class TestGpuPanelFallback:
    """gpu_panel should degrade gracefully when nvidia-smi is absent or fails."""

    def test_no_nvidia_smi_on_path(self):
        """When nvidia-smi is not found on PATH, show friendly fallback."""
        with mock.patch("sysglance.shutil.which", return_value=None):
            panel = sysglance.gpu_panel()
        rendered = panel.renderable.plain
        assert "No GPU detected" in rendered
        assert "nvidia-smi not found" in rendered

    def test_nvidia_smi_returns_error_code(self):
        """When nvidia-smi exits non-zero, show error message."""
        fake_result = subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=1, stdout="", stderr="fail"
        )
        with mock.patch("sysglance.shutil.which", return_value="/usr/bin/nvidia-smi"):
            with mock.patch("sysglance.subprocess.run", return_value=fake_result):
                panel = sysglance.gpu_panel()
        rendered = panel.renderable.plain
        assert "error" in rendered.lower()

    def test_nvidia_smi_returns_empty_output(self):
        """When nvidia-smi returns success but no data rows, show fallback."""
        fake_result = subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="", stderr=""
        )
        with mock.patch("sysglance.shutil.which", return_value="/usr/bin/nvidia-smi"):
            with mock.patch("sysglance.subprocess.run", return_value=fake_result):
                panel = sysglance.gpu_panel()
        rendered = panel.renderable.plain
        assert "No GPU data returned" in rendered

    def test_nvidia_smi_timeout_exception(self):
        """When nvidia-smi times out, show generic fallback."""
        with mock.patch("sysglance.shutil.which", return_value="/usr/bin/nvidia-smi"):
            with mock.patch(
                "sysglance.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5),
            ):
                panel = sysglance.gpu_panel()
        rendered = panel.renderable.plain
        assert "No GPU detected" in rendered

    def test_nvidia_smi_success(self):
        """When nvidia-smi returns valid CSV, panel should contain GPU info."""
        csv_line = "0, NVIDIA RTX 4090, 45, 2048, 24576, 55"
        fake_result = subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout=csv_line, stderr=""
        )
        with mock.patch("sysglance.shutil.which", return_value="/usr/bin/nvidia-smi"):
            with mock.patch("sysglance.subprocess.run", return_value=fake_result):
                panel = sysglance.gpu_panel()
        # The panel renderable is a joined Text — check the plain string
        rendered = panel.renderable.plain
        assert "GPU 0" in rendered
        assert "RTX 4090" in rendered
        assert "55°C" in rendered

    def test_nvidia_smi_malformed_csv_skipped(self):
        """Rows with fewer than 6 CSV fields are silently skipped."""
        csv_line = "0, NVIDIA RTX 4090, 45"  # only 3 fields
        fake_result = subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout=csv_line, stderr=""
        )
        with mock.patch("sysglance.shutil.which", return_value="/usr/bin/nvidia-smi"):
            with mock.patch("sysglance.subprocess.run", return_value=fake_result):
                panel = sysglance.gpu_panel()
        rendered = panel.renderable.plain
        assert "No GPU data returned" in rendered
