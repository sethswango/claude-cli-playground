# sysglance

A terminal system dashboard built with [Rich](https://github.com/Textualize/rich) and [psutil](https://github.com/giampaolo/psutil).

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)

## What it shows

| Panel | Content |
|-------|---------|
| **CPU Usage** | Per-core bar chart with color thresholds |
| **Memory** | RAM and swap with GiB details |
| **Disk Usage** | Per-mount table (size/used/free/%) |
| **Top Processes** | Top 5 by CPU with PID, name, CPU%, MEM% |
| **Network I/O** | Per-interface sent/received totals |
| **GPU Usage** | NVIDIA GPU utilization, VRAM, and temperature via `nvidia-smi` (gracefully shows "No GPU detected" if unavailable) |
| **Header** | Current time and system uptime |

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python sysglance.py
```

Press `Ctrl+C` to exit. The dashboard auto-refreshes every 2 seconds.

### Single snapshot

Use `--once` to print a single snapshot and exit (no live loop):

```bash
python sysglance.py --once
```

## Color coding

Bars shift color based on usage:
- **Green** — under 60%
- **Yellow** — 60–85%
- **Red** — above 85%
