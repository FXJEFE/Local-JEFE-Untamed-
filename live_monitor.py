#!/usr/bin/env python3
"""
Live CLI TUI Monitor for Larry G-Force
- Telegram Bot (sessions, heavy tasks, long prompts)
- Agent health indicators
- Resource usage
- Recent activity

Run with:
  python live_monitor.py

This is the reliable visual confirmation tool while the web dashboard (3777) is being fixed.
"""

import json
import time
import os
from datetime import datetime
from pathlib import Path
from collections import deque

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

PROJECT_ROOT = Path(__file__).parent.resolve()
LOGS_DIR = PROJECT_ROOT / "logs"
STATUS_FILE = LOGS_DIR / "telegram_live_status.json"
TELEGRAM_LOG = LOGS_DIR / "telegram_bot.log"

console = Console()

# Keep last N log lines
log_buffer = deque(maxlen=12)


def load_telegram_status():
    if not STATUS_FILE.exists():
        return {
            "timestamp": "never",
            "active_sessions": 0,
            "heavy_tasks": [],
            "long_prompt_builders": {},
            "heavy_task_details": {},
        }
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"timestamp": "error", "active_sessions": 0, "heavy_tasks": []}


def tail_log(path: Path, n=12):
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        return lines[-n:]
    except Exception:
        return []


def get_resource_snapshot():
    if not PSUTIL_OK:
        return "psutil not installed"
    try:
        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        return f"CPU: {cpu:5.1f}%   RAM: {mem.percent:5.1f}% ({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)"
    except Exception:
        return "Resource stats unavailable"


def build_layout():
    status = load_telegram_status()
    recent_logs = tail_log(TELEGRAM_LOG)

    # === Header ===
    header = Text("🚀 LARRY G-FORCE — LIVE MONITOR (CLI TUI)", style="bold cyan")
    header_panel = Panel(header, border_style="cyan")

    # === Telegram Sessions Panel ===
    sessions_table = Table(show_header=True, header_style="bold magenta", expand=True)
    sessions_table.add_column("Metric", style="cyan")
    sessions_table.add_column("Value", style="white")

    sessions_table.add_row("Active Sessions", str(status.get("active_sessions", 0)))
    heavy_count = len(status.get("heavy_tasks", []))
    sessions_table.add_row("Heavy Tasks Running", f"[red]{heavy_count}[/red]" if heavy_count > 0 else "0")

    long_builders = status.get("long_prompt_builders", {})
    sessions_table.add_row("Long Prompt Builders", str(len(long_builders)))

    sessions_panel = Panel(sessions_table, title="✈️ Telegram Bot Sessions", border_style="yellow")

    # === Heavy Work Details ===
    heavy_table = Table(show_header=True, header_style="bold red", expand=True)
    heavy_table.add_column("Chat ID", style="yellow")
    heavy_table.add_column("Active Task (truncated)", style="white")

    heavy_details = status.get("heavy_task_details", {})
    if heavy_details:
        for cid, task in heavy_details.items():
            short = (task or "")[:75] + ("..." if len(task or "") > 75 else "")
            heavy_table.add_row(str(cid), short)
    else:
        heavy_table.add_row("-", "No heavy /agent work running")

    heavy_panel = Panel(heavy_table, title="🔥 Active Heavy Work (Agentic Mode)", border_style="red")

    # === Long Prompt Builders ===
    prompt_table = Table(show_header=True, header_style="bold green", expand=True)
    prompt_table.add_column("Chat ID", style="cyan")
    prompt_table.add_column("Parts", style="white")
    prompt_table.add_column("Started", style="dim")
    prompt_table.add_column("Purpose", style="yellow")

    if long_builders:
        for cid, info in long_builders.items():
            started = info.get("started", "?")
            if started and "T" in started:
                started = started.split("T")[1][:8]
            purpose = info.get("meta", {}).get("purpose", "-")
            prompt_table.add_row(str(cid), str(info.get("parts", 0)), started, purpose)
    else:
        prompt_table.add_row("-", "-", "-", "No long prompts being built")

    prompt_panel = Panel(prompt_table, title="📝 Long Prompt Collection (1000+ lines)", border_style="green")

    # === Resources ===
    resources = get_resource_snapshot()
    res_panel = Panel(Text(resources, style="bold"), title="💻 Host Resources", border_style="blue")

    # === Recent Activity (log tail) ===
    log_text = Text()
    for line in recent_logs[-8:]:
        if "ERROR" in line or "❌" in line:
            log_text.append(line + "\n", style="red")
        elif "WARNING" in line:
            log_text.append(line + "\n", style="yellow")
        else:
            log_text.append(line + "\n", style="dim")
    if not recent_logs:
        log_text = Text("No recent logs (is telegram_bot.py running?)", style="dim red")

    log_panel = Panel(log_text, title="📜 Recent Telegram Activity (tail)", border_style="white", height=10)

    # === Instructions ===
    instructions = Text(
        "Press Ctrl+C to exit  |  Run alongside: python telegram_bot.py  |  Status file: logs/telegram_live_status.json",
        style="dim"
    )

    # Layout
    layout = Layout()
    layout.split_column(
        Layout(header_panel, size=3),
        Layout(sessions_panel, size=6),
        Layout(heavy_panel, size=6),
        Layout(prompt_panel, size=7),
        Layout(res_panel, size=3),
        Layout(log_panel, size=11),
        Layout(instructions, size=2),
    )
    return layout


def main():
    console.clear()
    console.print("[bold green]Starting Larry Live Monitor TUI...[/bold green] (updates every 2.5s)\n")

    with Live(build_layout(), refresh_per_second=0.4, screen=True, console=console) as live:
        try:
            while True:
                live.update(build_layout())
                time.sleep(2.5)
        except KeyboardInterrupt:
            console.print("\n[bold]Monitor stopped.[/bold]")


if __name__ == "__main__":
    main()
