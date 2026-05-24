"""
FXJEFE Local Larry - Memory Handoff Manager

When a new agent or different model is woken, it can load relevant context
from previous runs stored in the designated handoff folder.

The folder path is declared in the system prompt:
    data/agent_memory_handoff/
"""

from pathlib import Path
from typing import List, Optional
import json
from datetime import datetime

HANDOFF_DIR = Path("data/agent_memory_handoff")
HANDOFF_DIR.mkdir(parents=True, exist_ok=True)


def save_context_chunk(session_id: str, content: str, metadata: dict = None) -> Path:
    """Save a compressed context chunk for future agent/model handoff."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = HANDOFF_DIR / f"handoff_{session_id}_{timestamp}.json"

    data = {
        "session_id": session_id,
        "timestamp": timestamp,
        "content": content,
        "metadata": metadata or {}
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return filename


def load_recent_handoffs(limit: int = 5) -> List[dict]:
    """Load the most recent handoff chunks for a new agent instance."""
    files = sorted(HANDOFF_DIR.glob("handoff_*.json"), reverse=True)[:limit]
    results = []

    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                results.append(json.load(fh))
        except Exception:
            continue

    return results


def get_handoff_summary() -> str:
    """Return a short summary of available handoff memory for injection into prompts."""
    chunks = load_recent_handoffs(3)
    if not chunks:
        return "No previous agent memory available."

    summary = "Previous agent sessions available:\n"
    for c in chunks:
        summary += f"- {c.get('timestamp')} | Session: {c.get('session_id')}\n"
    return summary
