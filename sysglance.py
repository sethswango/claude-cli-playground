#!/usr/bin/env python3
"""sysglance — a terminal system dashboard powered by Rich.

Version: 0.2.0
Author: Collective
"""

__version__ = '0.2.0'

import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timedelta

import psutil
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.bar import Bar


def make_bar(label: str, pct: float, color: str = "green") -> Text:
    """Return a colored text bar like: label [████████░░░░] 62%"""
    width = 30
    filled = int(width * pct / 100)
    if pct > 85:
        color = "red"
    elif pct > 60:
        color = "yellow"
    bar = f"{'█' * filled}{'░' * (width - filled)}"
    return Text.assemble(
        (f"{label:<10} ", "bold white"),
        (f"[{bar}]", color),
        (f" {pct:5.1f}%", f"bold {color}"),
    )


def cpu_panel() -> Panel:
    """Per-core CPU usage bar chart."""
    lines: list[Text] = []
    percents = psutil.cpu_percent(percpu=True)
    for i, pct in enumerate(percents):
        lines.append(make_bar(f"Core {i}", pct))
    avg = psutil.cpu_percent()
    lines.append(Text(""))
    lines.append(make_bar("Average", avg, "cyan"))
    content = Text("\n").join(lines)
    return Panel(content, title="[bold cyan]CPU Usage[/]", border_style="cyan")


def mem_panel() -> Panel:
    """RAM and swap usage."""
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    used_gb = vm.used / (1 << 30)
    total_gb = vm.total / (1 << 30)
    sw_used = sw.used / (1 << 30)
    sw_total = sw.total / (1 << 30)
    lines = [
        make_bar("RAM", vm.percent),
        Text(f"           {used_gb:.1f} / {total_gb:.1f} GiB", style="dim"),
        Text(""),
        make_bar("Swap", sw.percent if sw.total else 0.0),
        Text(f"           {sw_used:.1f} / {sw_total:.1f} GiB", style="dim"),
    ]
    return Panel(Text("\n").join(lines), title="[bold magenta]Memory[/]", border_style="magenta")


def disk_panel() -> Panel:
    """Disk usage per mount point."""
    table = Table(expand=True, show_header=True, header_style="bold yellow")
    table.add_column("Mount", style="white", no_wrap=True)
    table.add_column("Size", justify="right")
    table.add_column("Used", justify="right")
    table.add_column("Free", justify="right")
    table.add_column("%", justify="right")
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        pct = u.percent
        color = "green" if pct < 60 else ("yellow" if pct < 85 else "red")
        table.add_row(
            part.mountpoint,
            f"{u.total / (1 << 30):.1f}G",
            f"{u.used / (1 << 30):.1f}G",
            f"{u.free / (1 << 30):.1f}G",
            f"[{color}]{pct:.0f}%[/]",
        )
    return Panel(table, title="[bold yellow]Disk Usage[/]", border_style="yellow")


def proc_panel() -> Panel:
    """Top 5 processes by CPU."""
    table = Table(expand=True, show_header=True, header_style="bold green")
    table.add_column("PID", justify="right", width=7)
    table.add_column("Name", ratio=2)
    table.add_column("CPU%", justify="right", width=7)
    table.add_column("MEM%", justify="right", width=7)
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            procs.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
    for info in procs[:5]:
        table.add_row(
            str(info["pid"]),
            (info["name"] or "?")[:25],
            f"{info['cpu_percent']:.1f}",
            f"{info['memory_percent']:.1f}" if info["memory_percent"] else "-",
        )
    return Panel(table, title="[bold green]Top Processes (CPU)[/]", border_style="green")


def net_panel() -> Panel:
    """Network I/O rates."""
    table = Table(expand=True, show_header=True, header_style="bold blue")
    table.add_column("Interface", style="white")
    table.add_column("Sent", justify="right")
    table.add_column("Recv", justify="right")
    counters = psutil.net_io_counters(pernic=True)
    for iface, io in sorted(counters.items()):
        if io.bytes_sent == 0 and io.bytes_recv == 0:
            continue
        table.add_row(
            iface,
            f"{io.bytes_sent / (1 << 20):.1f} MiB",
            f"{io.bytes_recv / (1 << 20):.1f} MiB",
        )
    return Panel(table, title="[bold blue]Network I/O[/]", border_style="blue")


def _docker_panel(msg: str) -> Panel:
    """Wrap a short message in a Docker-themed panel."""
    return Panel(
        Text(msg, style="dim italic"),
        title="[bold #ff6ac1]Docker Containers[/]",
        border_style="#ff6ac1",
    )


def _docker_container_row(table: Table, line: str) -> None:
    """Parse one JSON line from 'docker ps' and append a row to *table*."""
    try:
        c = json.loads(line)
    except json.JSONDecodeError:
        return
    status = c.get("Status", c.get("State", ""))
    color = "green" if "Up" in status else "yellow"
    ports = c.get("Ports", "")
    if len(ports) > 40:
        ports = ports[:37] + "..."
    table.add_row(
        c.get("Names", "?")[:20],
        c.get("Image", "?")[:25],
        f"[{color}]{status[:25]}[/]",
        ports,
    )


def _docker_table(lines: list[str]) -> Panel:
    """Build the Docker container table from parsed JSON lines."""
    table = Table(expand=True, show_header=True, header_style="bold #ff6ac1")
    table.add_column("Name", style="white", no_wrap=True, ratio=2)
    table.add_column("Image", ratio=2)
    table.add_column("Status", ratio=2)
    table.add_column("Ports", ratio=3)
    for line in lines:
        _docker_container_row(table, line)
    return Panel(table, title="[bold #ff6ac1]Docker Containers[/]", border_style="#ff6ac1")


def docker_panel() -> Panel:
    """Running Docker containers via 'docker ps'."""
    if not shutil.which("docker"):
        return _docker_panel("docker not found in PATH")
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            msg = result.stderr.strip().split("\n")[0] if result.stderr else "docker returned an error"
            return _docker_panel(msg[:80])
        lines = result.stdout.strip().splitlines()
        if not lines or not lines[0]:
            return _docker_panel("No running containers")
        return _docker_table(lines)
    except Exception:
        return _docker_panel("Could not query Docker")


def gpu_panel() -> Panel:
    """NVIDIA GPU utilization via nvidia-smi."""
    if not shutil.which("nvidia-smi"):
        return Panel(
            Text("No GPU detected (nvidia-smi not found)", style="dim italic"),
            title="[bold red]GPU Usage[/]",
            border_style="red",
        )
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return Panel(
                Text("nvidia-smi returned an error", style="bold red"),
                title="[bold red]GPU Usage[/]",
                border_style="red",
            )
        lines: list[Text] = []
        for row in result.stdout.strip().splitlines():
            parts = [p.strip() for p in row.split(",")]
            if len(parts) < 6:
                continue
            idx, name, util_pct, mem_used, mem_total, temp = parts
            util = float(util_pct)
            lines.append(make_bar(f"GPU {idx}", util))
            lines.append(
                Text(
                    f"           {name}  |  {mem_used}/{mem_total} MiB  |  {temp}°C",
                    style="dim",
                )
            )
            lines.append(Text(""))
        if not lines:
            return Panel(
                Text("No GPU data returned", style="dim italic"),
                title="[bold red]GPU Usage[/]",
                border_style="red",
            )
        content = Text("\n").join(lines)
        return Panel(content, title="[bold red]GPU Usage[/]", border_style="red")
    except Exception:
        return Panel(
            Text("No GPU detected", style="dim italic"),
            title="[bold red]GPU Usage[/]",
            border_style="red",
        )


def header_panel() -> Panel:
    """Clock and uptime."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    boot = datetime.fromtimestamp(psutil.boot_time())
    up = datetime.now() - boot
    days, rem = divmod(int(up.total_seconds()), 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    upstr = f"{days}d {hours}h {mins}m"
    txt = Text.assemble(
        ("  ⏰ ", ""), (now, "bold white"), ("    ⬆ up ", "dim"), (upstr, "bold white"),
        ("    📊 sysglance", "dim italic"),
    )
    return Panel(txt, style="on grey11", height=3)


def build_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="upper", ratio=2),
        Layout(name="lower", ratio=2),
    )
    layout["upper"].split_row(
        Layout(name="cpu", ratio=1),
        Layout(name="mem", ratio=1),
    )
    layout["lower"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1),
    )
    layout["left"].split_column(
        Layout(name="disk"),
        Layout(name="net"),
    )
    layout["right"].split_column(
        Layout(name="proc"),
        Layout(name="docker"),
        Layout(name="gpu"),
    )
    return layout


def refresh_panels(layout: Layout) -> None:
    """Update every panel in the layout."""
    layout["header"].update(header_panel())
    layout["cpu"].update(cpu_panel())
    layout["mem"].update(mem_panel())
    layout["disk"].update(disk_panel())
    layout["proc"].update(proc_panel())
    layout["net"].update(net_panel())
    layout["docker"].update(docker_panel())
    layout["gpu"].update(gpu_panel())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="sysglance — terminal system dashboard")
    parser.add_argument(
        "--once",
        action="store_true",
        help="print a single snapshot and exit instead of live-updating",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console = Console()
    layout = build_layout()
    # prime cpu_percent so first read isn't 0
    psutil.cpu_percent(percpu=True)
    for p in psutil.process_iter(["cpu_percent"]):
        pass
    time.sleep(0.5)

    if args.once:
        refresh_panels(layout)
        console.print(layout)
        return

    with Live(layout, console=console, refresh_per_second=2, screen=True):
        while True:
            refresh_panels(layout)
            time.sleep(2)


if __name__ == "__main__":
    main()
