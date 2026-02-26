"""Unit tests for sysglance.py — GPU fallback, --once arg parsing, color thresholds,
panel return types, and layout structure."""

import subprocess
import sys
import time
from collections import namedtuple
from unittest import mock

import pytest

import sysglance
from rich.layout import Layout
from rich.panel import Panel


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


# ---------------------------------------------------------------------------
# Helper factories for psutil mock objects
# ---------------------------------------------------------------------------

_svmem = namedtuple("svmem", ["total", "available", "percent", "used", "free"])
_sswap = namedtuple("sswap", ["total", "used", "free", "percent", "sin", "sout"])
_sdiskpart = namedtuple("sdiskpart", ["device", "mountpoint", "fstype", "opts"])
_sdiskusage = namedtuple("sdiskusage", ["total", "used", "free", "percent"])
_snetio = namedtuple("snetio", [
    "bytes_sent", "bytes_recv", "packets_sent", "packets_recv",
    "errin", "errout", "dropin", "dropout",
])


def _fake_process(pid, name, cpu_pct, mem_pct):
    """Return a mock that behaves like a psutil.Process from process_iter."""
    p = mock.MagicMock()
    p.info = {
        "pid": pid,
        "name": name,
        "cpu_percent": cpu_pct,
        "memory_percent": mem_pct,
    }
    return p


# ---------------------------------------------------------------------------
# parse_args — defaults and --once flag
# ---------------------------------------------------------------------------

class TestParseArgsDefaults:
    """Verify parse_args returns correct defaults for all known args."""

    def test_defaults_no_args(self):
        with mock.patch("sys.argv", ["sysglance"]):
            args = sysglance.parse_args()
        assert args.once is False

    def test_once_sets_true(self):
        with mock.patch("sys.argv", ["sysglance", "--once"]):
            args = sysglance.parse_args()
        assert args.once is True

    def test_namespace_has_once_attr(self):
        with mock.patch("sys.argv", ["sysglance"]):
            args = sysglance.parse_args()
        assert hasattr(args, "once")


# ---------------------------------------------------------------------------
# Each panel function returns a Rich Panel
# ---------------------------------------------------------------------------

class TestCpuPanelReturnsPanel:
    """cpu_panel should return a Panel with per-core info."""

    def test_returns_panel(self):
        with mock.patch("sysglance.psutil.cpu_percent") as mock_cpu:
            mock_cpu.side_effect = lambda percpu=False: [10.0, 20.0] if percpu else 15.0
            result = sysglance.cpu_panel()
        assert isinstance(result, Panel)

    def test_contains_core_labels(self):
        with mock.patch("sysglance.psutil.cpu_percent") as mock_cpu:
            mock_cpu.side_effect = lambda percpu=False: [5.0, 50.0, 90.0] if percpu else 48.3
            result = sysglance.cpu_panel()
        rendered = result.renderable.plain
        assert "Core 0" in rendered
        assert "Core 1" in rendered
        assert "Core 2" in rendered
        assert "Average" in rendered


class TestMemPanelReturnsPanel:
    """mem_panel should return a Panel with RAM and swap info."""

    def test_returns_panel(self):
        fake_vm = _svmem(total=16 * (1 << 30), available=8 * (1 << 30),
                         percent=50.0, used=8 * (1 << 30), free=8 * (1 << 30))
        fake_sw = _sswap(total=4 * (1 << 30), used=1 * (1 << 30),
                         free=3 * (1 << 30), percent=25.0, sin=0, sout=0)
        with mock.patch("sysglance.psutil.virtual_memory", return_value=fake_vm), \
             mock.patch("sysglance.psutil.swap_memory", return_value=fake_sw):
            result = sysglance.mem_panel()
        assert isinstance(result, Panel)

    def test_contains_ram_and_swap_labels(self):
        fake_vm = _svmem(total=16 * (1 << 30), available=8 * (1 << 30),
                         percent=50.0, used=8 * (1 << 30), free=8 * (1 << 30))
        fake_sw = _sswap(total=4 * (1 << 30), used=1 * (1 << 30),
                         free=3 * (1 << 30), percent=25.0, sin=0, sout=0)
        with mock.patch("sysglance.psutil.virtual_memory", return_value=fake_vm), \
             mock.patch("sysglance.psutil.swap_memory", return_value=fake_sw):
            result = sysglance.mem_panel()
        rendered = result.renderable.plain
        assert "RAM" in rendered
        assert "Swap" in rendered
        assert "GiB" in rendered

    def test_zero_swap(self):
        fake_vm = _svmem(total=8 * (1 << 30), available=4 * (1 << 30),
                         percent=50.0, used=4 * (1 << 30), free=4 * (1 << 30))
        fake_sw = _sswap(total=0, used=0, free=0, percent=0.0, sin=0, sout=0)
        with mock.patch("sysglance.psutil.virtual_memory", return_value=fake_vm), \
             mock.patch("sysglance.psutil.swap_memory", return_value=fake_sw):
            result = sysglance.mem_panel()
        assert isinstance(result, Panel)


class TestDiskPanelReturnsPanel:
    """disk_panel should return a Panel with a table of disk partitions."""

    def test_returns_panel(self):
        fake_parts = [_sdiskpart("/dev/sda1", "/", "ext4", "rw")]
        fake_usage = _sdiskusage(total=500 * (1 << 30), used=200 * (1 << 30),
                                 free=300 * (1 << 30), percent=40.0)
        with mock.patch("sysglance.psutil.disk_partitions", return_value=fake_parts), \
             mock.patch("sysglance.psutil.disk_usage", return_value=fake_usage):
            result = sysglance.disk_panel()
        assert isinstance(result, Panel)

    def test_returns_panel_with_no_partitions(self):
        with mock.patch("sysglance.psutil.disk_partitions", return_value=[]):
            result = sysglance.disk_panel()
        assert isinstance(result, Panel)

    def test_permission_error_skipped(self):
        fake_parts = [
            _sdiskpart("/dev/sda1", "/", "ext4", "rw"),
            _sdiskpart("/dev/sdb1", "/mnt/secret", "ext4", "rw"),
        ]
        fake_usage = _sdiskusage(total=500 * (1 << 30), used=200 * (1 << 30),
                                 free=300 * (1 << 30), percent=40.0)

        def _usage_side_effect(mp):
            if mp == "/mnt/secret":
                raise PermissionError("no access")
            return fake_usage

        with mock.patch("sysglance.psutil.disk_partitions", return_value=fake_parts), \
             mock.patch("sysglance.psutil.disk_usage", side_effect=_usage_side_effect):
            result = sysglance.disk_panel()
        assert isinstance(result, Panel)


class TestProcPanelReturnsPanel:
    """proc_panel should return a Panel with top processes."""

    def test_returns_panel(self):
        fake_procs = [
            _fake_process(1, "python", 45.0, 2.1),
            _fake_process(2, "chrome", 30.0, 8.5),
            _fake_process(3, "bash", 1.0, 0.3),
        ]
        with mock.patch("sysglance.psutil.process_iter", return_value=fake_procs):
            result = sysglance.proc_panel()
        assert isinstance(result, Panel)

    def test_returns_panel_empty_process_list(self):
        with mock.patch("sysglance.psutil.process_iter", return_value=[]):
            result = sysglance.proc_panel()
        assert isinstance(result, Panel)


class TestNetPanelReturnsPanel:
    """net_panel should return a Panel with network I/O counters."""

    def test_returns_panel(self):
        fake_counters = {
            "eth0": _snetio(bytes_sent=1024 * 1024, bytes_recv=2048 * 1024,
                            packets_sent=100, packets_recv=200,
                            errin=0, errout=0, dropin=0, dropout=0),
        }
        with mock.patch("sysglance.psutil.net_io_counters", return_value=fake_counters):
            result = sysglance.net_panel()
        assert isinstance(result, Panel)

    def test_skips_zero_traffic_interfaces(self):
        fake_counters = {
            "lo": _snetio(bytes_sent=0, bytes_recv=0,
                          packets_sent=0, packets_recv=0,
                          errin=0, errout=0, dropin=0, dropout=0),
            "eth0": _snetio(bytes_sent=5 * (1 << 20), bytes_recv=10 * (1 << 20),
                            packets_sent=100, packets_recv=200,
                            errin=0, errout=0, dropin=0, dropout=0),
        }
        with mock.patch("sysglance.psutil.net_io_counters", return_value=fake_counters):
            result = sysglance.net_panel()
        assert isinstance(result, Panel)

    def test_returns_panel_no_interfaces(self):
        with mock.patch("sysglance.psutil.net_io_counters", return_value={}):
            result = sysglance.net_panel()
        assert isinstance(result, Panel)


class TestHeaderPanelReturnsPanel:
    """header_panel should return a Panel with clock and uptime."""

    def test_returns_panel(self):
        boot_ts = time.time() - 86400
        with mock.patch("sysglance.psutil.boot_time", return_value=boot_ts):
            result = sysglance.header_panel()
        assert isinstance(result, Panel)

    def test_contains_uptime_info(self):
        boot_ts = time.time() - (2 * 86400 + 3 * 3600 + 15 * 60)
        with mock.patch("sysglance.psutil.boot_time", return_value=boot_ts):
            result = sysglance.header_panel()
        rendered = result.renderable.plain
        assert "sysglance" in rendered
        assert "2d" in rendered


class TestGpuPanelReturnsPanel:
    """gpu_panel should always return a Panel regardless of nvidia-smi availability."""

    def test_returns_panel_when_no_gpu(self):
        with mock.patch("sysglance.shutil.which", return_value=None):
            result = sysglance.gpu_panel()
        assert isinstance(result, Panel)

    def test_returns_panel_when_gpu_present(self):
        csv_line = "0, NVIDIA RTX 3080, 30, 1024, 10240, 60"
        fake_result = subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout=csv_line, stderr=""
        )
        with mock.patch("sysglance.shutil.which", return_value="/usr/bin/nvidia-smi"), \
             mock.patch("sysglance.subprocess.run", return_value=fake_result):
            result = sysglance.gpu_panel()
        assert isinstance(result, Panel)


# ---------------------------------------------------------------------------
# build_layout returns a Layout with expected sub-layouts
# ---------------------------------------------------------------------------

class TestBuildLayout:
    """build_layout should return a properly structured Layout."""

    def test_returns_layout(self):
        result = sysglance.build_layout()
        assert isinstance(result, Layout)

    def test_has_header_slot(self):
        layout = sysglance.build_layout()
        assert layout["header"] is not None

    def test_has_cpu_slot(self):
        layout = sysglance.build_layout()
        assert layout["cpu"] is not None

    def test_has_mem_slot(self):
        layout = sysglance.build_layout()
        assert layout["mem"] is not None

    def test_has_disk_slot(self):
        layout = sysglance.build_layout()
        assert layout["disk"] is not None

    def test_has_proc_slot(self):
        layout = sysglance.build_layout()
        assert layout["proc"] is not None

    def test_has_net_slot(self):
        layout = sysglance.build_layout()
        assert layout["net"] is not None

    def test_has_gpu_slot(self):
        layout = sysglance.build_layout()
        assert layout["gpu"] is not None

    def test_all_named_slots_present(self):
        layout = sysglance.build_layout()
        expected = {"header", "cpu", "mem", "disk", "proc", "net", "gpu"}
        for name in expected:
            assert layout[name] is not None


# ---------------------------------------------------------------------------
# --once subprocess exit code
# ---------------------------------------------------------------------------

class TestOnceSubprocess:
    """Running sysglance.py --once as a subprocess should exit cleanly."""

    def test_once_exits_with_rc_zero(self):
        result = subprocess.run(
            [sys.executable, "sysglance.py", "--once"],
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"sysglance.py --once exited with rc={result.returncode}\n"
            f"stderr: {result.stderr.decode()}"
        )
