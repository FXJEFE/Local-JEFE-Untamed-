#!/usr/bin/env python3
"""
FXJEFE Local Larry - Persistence & Logging Helpers

These functions implement the "Mandatory Persistent Saving & Logging" rules
from the system prompt. They are designed to be called by the main agent,
sub-agents, and tool handlers.

All logs are written in a structured way under data/ and larry_logs/ so they
can be loaded during memory handoff when a new agent/model wakes up.
"""

from pathlib import Path
from datetime import datetime
import json
import os

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "larry_logs"
HANDOFF_DIR = DATA_DIR / "agent_memory_handoff"

for d in (DATA_DIR, LOGS_DIR, HANDOFF_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _timestamp() -> str:
    return datetime.now().isoformat()


def _write_jsonl(filepath: Path, record: dict):
    """Append a JSON line to a log file."""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_skill_usage(skill_name: str, input_data: any, output: any, success: bool = True, metadata: dict = None):
    """Persist skill usage for future agent instances."""
    record = {
        "timestamp": _timestamp(),
        "type": "skill",
        "skill": skill_name,
        "input": str(input_data)[:2000],
        "output": str(output)[:2000],
        "success": success,
        "metadata": metadata or {}
    }
    _write_jsonl(LOGS_DIR / "skills.jsonl", record)
    return record


def log_task(task_description: str, status: str, result: any = None, metadata: dict = None):
    """Persist task execution."""
    record = {
        "timestamp": _timestamp(),
        "type": "task",
        "description": task_description,
        "status": status,
        "result": str(result)[:2000] if result else None,
        "metadata": metadata or {}
    }
    _write_jsonl(LOGS_DIR / "tasks.jsonl", record)
    return record


def log_tool_usage(tool_name: str, params: dict, result: any, source: str = "agent", metadata: dict = None):
    """Persist tool calls (MCP, FXJEFE, Kali, WSL, etc.)."""
    record = {
        "timestamp": _timestamp(),
        "type": "tool",
        "tool": tool_name,
        "params": params,
        "result": str(result)[:3000],
        "source": source,
        "metadata": metadata or {}
    }
    _write_jsonl(LOGS_DIR / "tool_usage.jsonl", record)
    return record


def log_spawned_agent(parent_session: str, sub_agent_id: str, model: str, injected_prompt_hash: str, context_summary: str, metadata: dict = None):
    """Record when a sub-agent or new model instance is spawned."""
    record = {
        "timestamp": _timestamp(),
        "type": "spawn",
        "parent_session": parent_session,
        "sub_agent_id": sub_agent_id,
        "model": model,
        "injected_prompt_hash": injected_prompt_hash,
        "context_summary": context_summary[:2000],
        "metadata": metadata or {}
    }
    _write_jsonl(LOGS_DIR / "spawned_agents.jsonl", record)
    return record


def log_model_routing(session_id: str, query_preview: str, chosen_model: str, reason: str, token_estimate: int, hardware_profile: str):
    """Record model routing decisions for continuity and analysis."""
    record = {
        "timestamp": _timestamp(),
        "type": "routing",
        "session": session_id,
        "query_preview": query_preview[:300],
        "chosen_model": chosen_model,
        "reason": reason,
        "token_estimate": token_estimate,
        "hardware_profile": hardware_profile
    }
    _write_jsonl(LOGS_DIR / "model_routing.jsonl", record)
    return record


def log_wsl_kali_usage(command: str, output: str, success: bool, metadata: dict = None):
    """Persist WSL Kali command usage."""
    record = {
        "timestamp": _timestamp(),
        "type": "wsl_kali",
        "command": command[:500],
        "output": output[:3000],
        "success": success,
        "metadata": metadata or {}
    }
    _write_jsonl(LOGS_DIR / "wsl_kali_usage.jsonl", record)
    return record


def log_dynamic_context_action(session_id: str, action: str, context_percent: float, model: str, details: str):
    """Record dynamic context management events (summarization, etc.)."""
    record = {
        "timestamp": _timestamp(),
        "type": "context",
        "session": session_id,
        "action": action,           # "summarize", "compress", "switch_model", etc.
        "context_percent": round(context_percent, 1),
        "model": model,
        "details": details[:1000]
    }
    _write_jsonl(LOGS_DIR / "dynamic_context.jsonl", record)
    return record


def get_persistence_summary(limit: int = 5) -> dict:
    """Quick summary of recent persistence activity (useful for handoff injection)."""
    summary = {}
    for name in ["skills", "tasks", "tool_usage", "spawned_agents", "model_routing", "wsl_kali_usage", "dynamic_context"]:
        path = LOGS_DIR / f"{name}.jsonl"
        if path.exists():
            lines = path.read_text(encoding="utf-8").strip().splitlines()[-limit:]
            summary[name] = [json.loads(l) for l in lines if l.strip()]
        else:
            summary[name] = []
    return summary
