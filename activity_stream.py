#!/usr/bin/env python3
"""
Activity Stream — Shared event bus for Agent-Larry components.
Writes JSON events to a rolling log file that the dashboard reads via API.
Used by: agent_v2.py, telegram_bot.py, dashboard_hub.py
"""

import json
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

STREAM_DIR = Path(__file__).parent.resolve() / "logs"
STREAM_DIR.mkdir(exist_ok=True)
STREAM_FILE = STREAM_DIR / "activity_stream.jsonl"
MAX_EVENTS = 500  # Rolling cap — prune oldest when exceeded


class ActivityStream:
    """Lightweight event emitter that appends JSON lines to a shared file."""

    _lock = threading.Lock()

    # Event types
    QUERY_RECEIVED = "query_received"
    MODEL_SELECTED = "model_selected"
    CONTEXT_BUDGET = "context_budget"
    RAG_SEARCH     = "rag_search"
    TOOL_DISPATCH  = "tool_dispatch"
    THINKING       = "thinking"
    GENERATING     = "generating"
    RESPONSE_DONE  = "response_done"
    EXECUTION      = "execution"      # For bash, WSL, code runs
    TOOL_CALL      = "tool_call"      # Detailed tool execution
    ERROR          = "error"
    SYSTEM         = "system"

    def __init__(self, source: str = "unknown"):
        """
        Args:
            source: identifier like 'agent_v2', 'telegram_bot', 'ollama'
        """
        self.source = source

    def emit(self, event_type: str, message: str, detail: Optional[dict] = None):
        """Write one event to the stream file."""
        event = {
            "ts": time.time(),
            "time": datetime.now().strftime("%H:%M:%S"),
            "source": self.source,
            "type": event_type,
            "msg": message,
        }
        if detail:
            event["detail"] = detail
        try:
            with self._lock:
                with open(STREAM_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")
        except Exception:
            pass  # Never crash the host process

    @staticmethod
    def read_recent(since: float = 0, limit: int = 100) -> list:
        """Read events newer than `since` (unix timestamp). Returns list of dicts."""
        if not STREAM_FILE.exists():
            return []
        events = []
        try:
            with open(STREAM_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        if ev.get("ts", 0) > since:
                            events.append(ev)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return events[-limit:]

    @staticmethod
    def prune():
        """Keep only the last MAX_EVENTS lines."""
        if not STREAM_FILE.exists():
            return
        try:
            with open(STREAM_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > MAX_EVENTS:
                with open(STREAM_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-MAX_EVENTS:])
        except Exception:
            pass


# ── Lightweight shared status for Command Central v4.0 ────────────────────────
STATUS_FILE = STREAM_DIR / "agent_status.json"

def report_status(source: str, status: str = "IDLE", model: str = None, context_tokens: int = None, extra: dict = None):
    """Update the shared status file so the dashboard can show live agent state."""
    try:
        if STATUS_FILE.exists():
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}

        entry = {
            "status": status,
            "model": model,
            "context_tokens": context_tokens,
            "last_update": time.time(),
            "time": datetime.now().strftime("%H:%M:%S"),
        }
        if extra:
            entry.update(extra)
        data[source] = entry

        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def read_status() -> dict:
    """Read current status of all agents."""
    if not STATUS_FILE.exists():
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
