"""
path_resolver.py — Dynamic path and config resolution for FXJEFE / Larry pipelines.

Provides get_paths() and get_config() so that pipeline scripts (run_pipeline_enhanced.py,
run_production_pipeline.py, etc.) can run without hard-coded Windows paths.

This is a compatibility shim. It prefers larry_config.json and the standard project layout,
with fallbacks for the older "Config/config.json" layout seen in some scripts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _find_project_root(start: Optional[Path] = None) -> Path:
    """Walk upward from the caller's file or cwd until we find recognizable markers."""
    markers = ("requirements.txt", "larry_config.json", ".git", "pyproject.toml", "setup_larry.py")
    p = (start or Path.cwd()).resolve()
    for _ in range(8):  # safety bound
        if any((p / m).exists() for m in markers):
            return p
        if p.parent == p:
            break
        p = p.parent
    # Fallback: directory containing this file
    return Path(__file__).parent.resolve()


PROJECT_ROOT: Path = _find_project_root()

# Common candidate config locations (support both old FXJEFE layout and current Larry layout)
_CANDIDATE_CONFIGS = [
    PROJECT_ROOT / "Config" / "config.json",          # old pipelinerun.py expectation
    PROJECT_ROOT / "config" / "config.json",
    PROJECT_ROOT / "config" / "larry_config.json",
    PROJECT_ROOT / "larry_config.json",
]


def _load_config_dict() -> Dict[str, Any]:
    for candidate in _CANDIDATE_CONFIGS:
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


_CONFIG_CACHE: Dict[str, Any] = _load_config_dict()


class Paths:
    """Container for resolved project paths. Add methods as needed by your pipelines."""

    def __init__(self, root: Path):
        self.project_root: Path = root
        self.root = root  # alias used in some scripts

        # Standard directories
        self.data_dir: Path = root / "data"
        self.logs_dir: Path = root / "logs"
        self.exports_dir: Path = root / "exports"
        self.config_dir: Path = root / "config"
        self.scripts_dir: Path = root / "scripts"
        self.sandbox_dir: Path = root / "sandbox"
        self.chroma_dir: Path = root / "chroma_db"

        # Also expose the common names some older scripts expect
        self.logs_path: Path = self.logs_dir
        self.data_path: Path = self.data_dir

        # Create the ones we can safely create
        for d in (self.logs_dir, self.data_dir, self.exports_dir, self.sandbox_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    def get_log_path(self, name: str = "pipeline.log") -> Path:
        """Return a path inside the logs directory."""
        if not name.lower().endswith((".log", ".txt", ".json")):
            name += ".log"
        return self.logs_dir / name

    def get_data_path(self, name: str = "") -> Path:
        p = self.data_dir
        if name:
            p = p / name
        return p

    def __getattr__(self, item: str) -> Any:
        # Allow scripts to do paths.some_custom_dir without crashing
        if item.endswith("_dir") or item.endswith("_path"):
            p = self.project_root / item.replace("_dir", "").replace("_path", "")
            return p
        raise AttributeError(f"Paths has no attribute {item}")


def get_paths() -> Paths:
    """Main entry point expected by pipeline runners."""
    return Paths(PROJECT_ROOT)


def get_config() -> Dict[str, Any]:
    """Return the loaded configuration dict (or empty dict if none found)."""
    return dict(_CONFIG_CACHE)  # return a copy


def get_active_account() -> Optional[str]:
    """Placeholder for trading-account helpers some scripts reference."""
    cfg = _CONFIG_CACHE
    return cfg.get("active_account") or cfg.get("mt5", {}).get("account")


# Convenience re-exports
__all__ = ["get_paths", "get_config", "get_active_account", "Paths", "PROJECT_ROOT"]


if __name__ == "__main__":
    p = get_paths()
    c = get_config()
    print(f"Project root: {p.project_root}")
    print(f"Config keys: {list(c.keys())[:8] if c else '(none found)'}")
    print(f"Log path example: {p.get_log_path()}")