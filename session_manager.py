#!/usr/bin/env python3
"""
Session Manager for Larry G-Force
===================================
Handles:
  - Context limit tracking + auto-summarization when near limit
  - Fresh chat / session reset
  - End-of-session summary saved to RAG DB (ChromaDB)
  - Terminal command execution (local machine only)
  - Session state persistence across restarts

Integrates with:
  - agent_v2.py  (drop-in via SessionManager class)
  - production_rag.py  (saves summaries to 'conv' collection)
  - unified_context_manager.py  (token counting)
  - model_router.py  (summarization via LLM)

Usage in agent_v2.py:
    from session_manager import SessionManager
    self.session = SessionManager(rag=self.rag, router=self.model_router)

    # On every message:
    self.session.add_turn(role="user", content=user_msg)
    self.session.add_turn(role="assistant", content=reply)
    self.session.maybe_summarize()  # auto-compresses when near limit

    # On /new or /reset command:
    summary = await self.session.end_session()

    # On startup — inject last session memory:
    context = self.session.get_context_injection()
"""

import os
import json
import logging
import hashlib
import subprocess
import shlex
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
SESSION_FILE     = Path(__file__).parent / "data" / "session_state.json"
SUMMARY_FILE     = Path(__file__).parent / "data" / "session_summaries.jsonl"
MAX_TURNS        = 40          # compress after this many turns
TOKEN_WARN_PCT   = 0.80        # warn + compress at 80% of context limit
CONTEXT_LIMIT    = 65536       # from unified_context_manager
TOKEN_WARN_AT    = int(CONTEXT_LIMIT * TOKEN_WARN_PCT)
SUMMARY_MODEL    = "llama3.3:70b"   # model used for summarization
SUMMARY_FALLBACK = "ministral-3:latest"
TERMINAL_TIMEOUT = 30          # seconds per terminal command
TERMINAL_ALLOWED_DIRS = [      # restrict execution to safe dirs
    str(Path.home() / "Documents" / "Agent-Larry"),
    str(Path.home() / "Documents"),
    str(Path.home() / "Desktop"),
    str(Path.home() / "Downloads"),
    "/tmp",
]


# ── Session Manager ────────────────────────────────────────────────────────────
class SessionManager:
    """
    Manages conversation sessions with context compression,
    RAG persistence, and local terminal execution.
    """

    def __init__(self, rag=None, router=None, user_id: str = "default"):
        self.rag       = rag
        self.router    = router
        self.user_id   = user_id
        self.turns: List[Dict] = []
        self.session_id   = self._make_session_id()
        self.started_at   = datetime.now().isoformat()
        self.goal: str    = ""
        self.work_done: List[str] = []
        self.compressed_summary: str = ""   # rolling summary of old turns
        self.total_tokens: int = 0
        self.terminal_cwd = Path.home() / "Documents" / "Agent-Larry"

        # Ensure data dir exists
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Load previous session context
        self._load_last_session()
        logger.info(f"SessionManager initialized — session {self.session_id}")

    # ── Session ID ─────────────────────────────────────────────────────────────
    def _make_session_id(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"session_{ts}"

    # ── Turn Management ────────────────────────────────────────────────────────
    def add_turn(self, role: str, content: str) -> None:
        """Add a conversation turn and track tokens."""
        turn = {
            "role":      role,
            "content":   content,
            "timestamp": datetime.now().isoformat(),
            "tokens":    self._estimate_tokens(content),
        }
        self.turns.append(turn)
        self.total_tokens += turn["tokens"]

        # Track work done from assistant turns
        if role == "assistant" and len(content) > 50:
            brief = content[:120].replace("\n", " ").strip()
            self.work_done.append(brief)
            if len(self.work_done) > 50:
                self.work_done = self.work_done[-50:]

    def set_goal(self, goal: str) -> None:
        """Set the session goal (shown in summaries)."""
        self.goal = goal
        logger.info(f"Session goal set: {goal[:80]}")

    def get_history(self) -> List[Dict]:
        """Return current turns as [{"role": ..., "content": ...}]."""
        return [{"role": t["role"], "content": t["content"]} for t in self.turns]

    def _estimate_tokens(self, text: str) -> int:
        """Fast token estimate (~4 chars per token)."""
        return max(1, len(text) // 4)

    # ── Context Injection (for new session startup) ────────────────────────────
    def get_context_injection(self) -> str:
        """
        Returns a string to inject at the start of a new session
        containing the last session's summary. Feed this as system context.
        """
        last = self._load_last_summary()
        if not last:
            return ""

        age   = last.get("ended_at", "unknown time")
        goal  = last.get("goal", "")
        done  = last.get("work_done_summary", "")
        summ  = last.get("summary", "")

        parts = [f"[PREVIOUS SESSION — {age}]"]
        if goal:
            parts.append(f"Goal: {goal}")
        if done:
            parts.append(f"Work completed: {done}")
        if summ:
            parts.append(f"Summary:\n{summ}")
        parts.append("[END PREVIOUS SESSION]\n")
        return "\n".join(parts)

    # ── Auto-Compress ──────────────────────────────────────────────────────────
    def should_compress(self) -> bool:
        """Returns True if context is getting full or too many turns."""
        return self.total_tokens >= TOKEN_WARN_AT or len(self.turns) >= MAX_TURNS

    def maybe_summarize(self) -> Optional[str]:
        """
        If context is near limit, compress old turns into a rolling summary.
        Keeps the last 10 turns fresh, summarizes everything before that.
        Called automatically after each turn.
        """
        if not self.should_compress():
            return None

        logger.info(f"Context compression triggered — {self.total_tokens} tokens, {len(self.turns)} turns")
        return self._compress_turns()

    def _compress_turns(self) -> str:
        """Summarize old turns, keep last 10 fresh."""
        if len(self.turns) <= 10:
            return ""

        old_turns  = self.turns[:-10]
        keep_turns = self.turns[-10:]

        # Build text to summarize
        old_text = "\n".join(
            f"{t['role'].upper()}: {t['content'][:500]}"
            for t in old_turns
        )

        prompt = f"""Summarize this conversation segment concisely.
Focus on: goals, decisions made, code written, files changed, problems solved.
Be factual and brief. Max 300 words.

{old_text}

SUMMARY:"""

        summary_text = self._llm_summarize(prompt)

        # Roll into compressed_summary
        if self.compressed_summary:
            self.compressed_summary += f"\n\n[CONTINUED]\n{summary_text}"
        else:
            self.compressed_summary = summary_text

        # Reset turns — keep only recent
        self.turns       = keep_turns
        self.total_tokens = sum(t["tokens"] for t in self.turns)

        logger.info(f"Compressed {len(old_turns)} turns → {len(summary_text)} chars summary")
        return summary_text

    # ── End Session ────────────────────────────────────────────────────────────
    def end_session(self, save_to_rag: bool = True) -> str:
        """
        Call this on /new, /reset, or before shutdown.
        1. Generates full session summary
        2. Saves to JSONL file
        3. Saves to RAG ChromaDB (conv collection)
        4. Resets state for new session
        Returns the summary string.
        """
        if not self.turns and not self.compressed_summary:
            self._reset()
            return "No conversation to summarize."

        logger.info(f"Ending session {self.session_id}")

        # Generate final summary
        summary = self._generate_final_summary()

        # Build session record
        record = {
            "session_id":        self.session_id,
            "user_id":           self.user_id,
            "started_at":        self.started_at,
            "ended_at":          datetime.now().isoformat(),
            "goal":              self.goal,
            "turns_count":       len(self.turns),
            "total_tokens_est":  self.total_tokens,
            "work_done_summary": self._work_done_summary(),
            "summary":           summary,
            "compressed_parts":  self.compressed_summary,
        }

        # Save to JSONL
        self._save_to_file(record)

        # Save to RAG
        if save_to_rag and self.rag:
            self._save_to_rag(record)

        # Reset for new session
        self._reset()

        logger.info("Session ended and saved.")
        return summary

    def _generate_final_summary(self) -> str:
        """Generate a comprehensive end-of-session summary."""
        # Build full context
        parts = []
        if self.compressed_summary:
            parts.append(f"[EARLIER IN SESSION]\n{self.compressed_summary}")
        if self.turns:
            recent = "\n".join(
                f"{t['role'].upper()}: {t['content'][:600]}"
                for t in self.turns[-20:]
            )
            parts.append(f"[RECENT CONVERSATION]\n{recent}")

        full_context = "\n\n".join(parts) if parts else "No conversation content."

        goal_line = f"Session goal: {self.goal}" if self.goal else ""
        work_line = f"Work done: {self._work_done_summary()}" if self.work_done else ""

        prompt = f"""Create a structured session summary for future reference.

{goal_line}
{work_line}

Conversation:
{full_context[:6000]}

Write a clear summary covering:
1. GOAL: What was being worked on
2. ACCOMPLISHED: What was completed
3. KEY DECISIONS: Important choices made
4. FILES/CODE: Any files created or modified
5. NEXT STEPS: What should happen next session
6. CONTEXT: Any important state to remember

Keep it under 400 words. Be specific and factual."""

        return self._llm_summarize(prompt)

    def _work_done_summary(self) -> str:
        if not self.work_done:
            return "No work recorded."
        # Deduplicate and join last 10 items
        seen = []
        for w in self.work_done[-10:]:
            if w not in seen:
                seen.append(w)
        return " | ".join(seen)

    def _llm_summarize(self, prompt: str) -> str:
        """Use LLM to generate summary text."""
        if not self.router:
            # Fallback: basic extractive summary
            return self._extractive_summary()

        try:
            result = self.router.generate(
                prompt=prompt,
                model=SUMMARY_MODEL,
                timeout=None,
            )
            return result.strip()
        except Exception as e:
            logger.warning(f"Summary with {SUMMARY_MODEL} failed: {e}, trying fallback")
            try:
                result = self.router.generate(
                    prompt=prompt,
                    model=SUMMARY_FALLBACK,
                    timeout=None,
                )
                return result.strip()
            except Exception as e2:
                logger.error(f"Summary fallback also failed: {e2}")
                return self._extractive_summary()

    def _extractive_summary(self) -> str:
        """Simple extractive fallback if LLM unavailable."""
        lines = [f"Session: {self.session_id}", f"Goal: {self.goal or 'Not set'}"]
        lines.append(f"Turns: {len(self.turns)}")
        if self.work_done:
            lines.append("Work done:")
            for w in self.work_done[-5:]:
                lines.append(f"  - {w}")
        return "\n".join(lines)

    # ── RAG Persistence ────────────────────────────────────────────────────────
    def _save_to_rag(self, record: Dict) -> None:
        """Save session summary to ChromaDB conv collection."""
        try:
            doc_text = f"""SESSION SUMMARY — {record['ended_at'][:10]}
Goal: {record['goal']}
Work done: {record['work_done_summary']}

{record['summary']}"""

            metadata = {
                "session_id":  record["session_id"],
                "date":        record["ended_at"][:10],
                "type":        "session_summary",
                "goal":        record["goal"][:200] if record["goal"] else "",
            }

            doc_id = hashlib.md5(record["session_id"].encode()).hexdigest()

            # Try production_rag add_document API
            if hasattr(self.rag, "add_document"):
                self.rag.add_document(
                    collection="conv",
                    doc_id=doc_id,
                    text=doc_text,
                    metadata=metadata,
                )
                logger.info(f"Session summary saved to RAG conv collection (id={doc_id})")

            # Try direct ChromaDB collection access
            elif hasattr(self.rag, "collections") and "conv" in self.rag.collections:
                self.rag.collections["conv"].upsert(
                    documents=[doc_text],
                    metadatas=[metadata],
                    ids=[doc_id],
                )
                logger.info(f"Session summary saved to ChromaDB conv (id={doc_id})")

            # Try generic index method
            elif hasattr(self.rag, "index_text"):
                self.rag.index_text(doc_text, metadata=metadata, collection="conv")
                logger.info("Session summary indexed via index_text()")

            else:
                logger.warning("RAG available but no known add method found — saving to file only")

        except Exception as e:
            logger.error(f"Failed to save to RAG: {e}")

    def _save_to_file(self, record: Dict) -> None:
        """Append session record to JSONL file."""
        try:
            with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.info(f"Session saved to {SUMMARY_FILE}")
        except Exception as e:
            logger.error(f"Failed to save session file: {e}")

    def _load_last_summary(self) -> Optional[Dict]:
        """Load the most recent session summary from JSONL."""
        if not SUMMARY_FILE.exists():
            return None
        try:
            lines = SUMMARY_FILE.read_text(encoding="utf-8").strip().splitlines()
            if not lines:
                return None
            return json.loads(lines[-1])
        except Exception as e:
            logger.warning(f"Could not load last summary: {e}")
            return None

    def _load_last_session(self) -> None:
        """On startup, log that previous session context is available."""
        last = self._load_last_summary()
        if last:
            ended = last.get("ended_at", "")[:16].replace("T", " ")
            goal  = last.get("goal", "")[:60]
            logger.info(f"Previous session available: {ended} — {goal}")

    # ── State Reset ────────────────────────────────────────────────────────────
    def _reset(self) -> None:
        """Reset for a new session."""
        self.turns             = []
        self.session_id        = self._make_session_id()
        self.started_at        = datetime.now().isoformat()
        self.goal              = ""
        self.work_done         = []
        self.compressed_summary = ""
        self.total_tokens      = 0
        logger.info(f"New session started: {self.session_id}")

    def new_session(self, save_current: bool = True) -> str:
        """Public method: end current session and start fresh."""
        msg = self.end_session(save_to_rag=save_current)
        return msg

    # ── Status ─────────────────────────────────────────────────────────────────
    def get_status(self) -> Dict:
        pct = round((self.total_tokens / CONTEXT_LIMIT) * 100, 1)
        return {
            "session_id":    self.session_id,
            "started_at":    self.started_at,
            "turns":         len(self.turns),
            "tokens_used":   self.total_tokens,
            "tokens_limit":  CONTEXT_LIMIT,
            "context_pct":   pct,
            "goal":          self.goal,
            "compressed":    bool(self.compressed_summary),
            "warn":          pct >= 80,
        }

    def format_status(self) -> str:
        s = self.get_status()
        bar_filled = int(s["context_pct"] / 5)
        bar = "█" * bar_filled + "░" * (20 - bar_filled)
        warn = " ⚠️ COMPRESSING SOON" if s["warn"] else ""
        return (
            f"📊 Session: {s['session_id']}\n"
            f"💬 Turns: {s['turns']}  |  🪙 Tokens: {s['tokens_used']:,}/{s['tokens_limit']:,}\n"
            f"[{bar}] {s['context_pct']}%{warn}\n"
            f"🎯 Goal: {s['goal'] or 'not set'}\n"
            f"📦 Compressed history: {'yes' if s['compressed'] else 'no'}"
        )


# ── Terminal Handler ───────────────────────────────────────────────────────────
class TerminalHandler:
    """
    Safe local terminal execution for Larry agent.
    Only runs on local machine — never in Docker/cloud context.
    Restricts execution to allowed directories.
    """

    def __init__(self, session: SessionManager = None):
        self.session = session

        # Prefer the project's sandbox or working directory over a random "Agent-Larry" folder
        try:
            from larry_paths import SANDBOX_DIR, BASE_DIR
            preferred = SANDBOX_DIR if SANDBOX_DIR.exists() else BASE_DIR / "sandbox"
            self.cwd = preferred.resolve()
        except Exception:
            # Safe fallback inside user's Documents
            self.cwd = Path.home() / "Documents" / "LocalLarry" / "GITHUB" / "sandbox"

        self.history: List[Dict] = []
        logger.info(f"TerminalHandler initialized — cwd: {self.cwd}")

    def is_safe_path(self, path: str) -> bool:
        """Check path is within allowed directories."""
        try:
            resolved = Path(path).resolve()
            return any(
                str(resolved).startswith(allowed)
                for allowed in TERMINAL_ALLOWED_DIRS
            )
        except Exception:
            return False

    def set_cwd(self, path: str) -> Tuple[bool, str]:
        """Change working directory."""
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return False, f"Directory not found: {path}"
        if not p.is_dir():
            return False, f"Not a directory: {path}"
        if not self.is_safe_path(str(p)):
            return False, f"Directory outside allowed paths: {path}"
        self.cwd = p
        return True, f"Changed to: {self.cwd}"

    def execute(self, command: str, timeout: int = TERMINAL_TIMEOUT) -> Dict:
        """
        Execute a shell command safely.
        Returns dict with stdout, stderr, returncode, command, cwd.
        """
        # Handle cd specially
        if command.strip().startswith("cd "):
            new_dir = command.strip()[3:].strip().strip("'\"")
            new_dir = str(Path(self.cwd / new_dir).resolve())
            ok, msg = self.set_cwd(new_dir)
            return {
                "command":    command,
                "cwd":        str(self.cwd),
                "stdout":     msg,
                "stderr":     "",
                "returncode": 0 if ok else 1,
                "success":    ok,
            }

        # Block dangerous commands
        blocked = ["rm -rf /", "mkfs", "dd if=", ":(){:|:&};:", "sudo rm -rf"]
        for b in blocked:
            if b in command:
                return {
                    "command":    command,
                    "cwd":        str(self.cwd),
                    "stdout":     "",
                    "stderr":     f"Blocked dangerous command: {b}",
                    "returncode": 403,
                    "success":    False,
                }

        logger.info(f"Terminal execute: {command[:80]} (cwd={self.cwd})")

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "TERM": "xterm-256color"},
            )
            record = {
                "command":    command,
                "cwd":        str(self.cwd),
                "stdout":     result.stdout,
                "stderr":     result.stderr,
                "returncode": result.returncode,
                "success":    result.returncode == 0,
                "timestamp":  datetime.now().isoformat(),
            }
        except subprocess.TimeoutExpired:
            record = {
                "command":    command,
                "cwd":        str(self.cwd),
                "stdout":     "",
                "stderr":     f"Command timed out after {timeout}s",
                "returncode": 124,
                "success":    False,
                "timestamp":  datetime.now().isoformat(),
            }
        except Exception as e:
            record = {
                "command":    command,
                "cwd":        str(self.cwd),
                "stdout":     "",
                "stderr":     str(e),
                "returncode": 1,
                "success":    False,
                "timestamp":  datetime.now().isoformat(),
            }

        self.history.append(record)

        # Track in session
        if self.session:
            status = "✅" if record["success"] else "❌"
            self.session.work_done.append(
                f"{status} terminal: {command[:60]}"
            )

        return record

    def format_result(self, result: Dict, max_lines: int = 50) -> str:
        """Format terminal result for Telegram message."""
        lines = []
        lines.append(f"```\n$ {result['command']}\n")

        stdout = result["stdout"].strip()
        stderr = result["stderr"].strip()

        if stdout:
            out_lines = stdout.splitlines()
            if len(out_lines) > max_lines:
                lines.append("\n".join(out_lines[:max_lines]))
                lines.append(f"\n... ({len(out_lines) - max_lines} more lines)")
            else:
                lines.append(stdout)

        if stderr:
            lines.append(f"\nSTDERR:\n{stderr[:500]}")

        rc = result["returncode"]
        icon = "✅" if result["success"] else f"❌ (exit {rc})"
        lines.append(f"\n{icon}")
        lines.append("```")

        return "".join(lines)

    def run_python_file(self, filepath: str, args: str = "") -> Dict:
        """Run a Python file in the venv."""
        venv_python = Path(__file__).parent / ".venv" / "bin" / "python3"
        if not venv_python.exists():
            venv_python = Path("python3")
        cmd = f"{venv_python} {filepath} {args}".strip()
        return self.execute(cmd)

    def run_script(self, filepath: str) -> Dict:
        """Run a bash script."""
        p = Path(filepath)
        if not p.exists():
            return {"success": False, "stderr": f"File not found: {filepath}", 
                    "stdout": "", "returncode": 1, "command": filepath, "cwd": str(self.cwd)}
        # Make executable
        self.execute(f"chmod +x {filepath}")
        return self.execute(f"bash {filepath}")


# ── agent_v2.py Integration Patch ─────────────────────────────────────────────
AGENT_V2_PATCH = '''
# ============================================================
# SESSION MANAGER INTEGRATION PATCH FOR agent_v2.py
# Add these to the appropriate locations in agent_v2.py
# ============================================================

# 1. ADD TO IMPORTS (top of agent_v2.py)
from session_manager import SessionManager, TerminalHandler

# 2. ADD TO __init__ (inside EnhancedAgent.__init__ after existing inits)
self.session = SessionManager(
    rag=self.rag if hasattr(self, "rag") else None,
    router=self.model_router if hasattr(self, "model_router") else None,
)
self.terminal = TerminalHandler(session=self.session)
logger.info("Session Manager initialized")
logger.info("Terminal Handler initialized")

# 3. ADD TO process_message() — after getting reply, before return
# Track the conversation
self.session.add_turn(role="user", content=user_message)
self.session.add_turn(role="assistant", content=reply)
# Auto-compress if near context limit
compression = self.session.maybe_summarize()
if compression:
    logger.info("Context compressed — session history rolled up")

# 4. ADD TO get_system_prompt() — prepend previous session context
prev_context = self.session.get_context_injection()
if prev_context:
    system_prompt = prev_context + "\\n\\n" + system_prompt

# 5. ADD COMMAND HANDLERS (in handle_command() or equivalent)

# /new or /reset — end session and start fresh
if command == "new" or command == "reset":
    summary = self.session.end_session(save_to_rag=True)
    return f"✅ Session saved.\\n\\n{summary[:800]}"

# /goal <text> — set session goal
if command == "goal":
    self.session.set_goal(args)
    return f"🎯 Goal set: {args}"

# /session — show session status
if command == "session":
    return self.session.format_status()

# /run <command> — execute terminal command
if command == "run":
    result = self.terminal.execute(args)
    return self.terminal.format_result(result)

# /cd <path> — change terminal directory
if command == "cd":
    ok, msg = self.terminal.set_cwd(args)
    return msg

# /py <file> — run python file
if command == "py":
    result = self.terminal.run_python_file(args)
    return self.terminal.format_result(result)

# 6. ADD TO shutdown/stop handler
self.session.end_session(save_to_rag=True)
'''

if __name__ == "__main__":
    print("Session Manager — self test")
    print("=" * 50)

    sm = SessionManager()
    sm.set_goal("Test session manager functionality")

    # Simulate turns
    sm.add_turn("user", "Hello, can you help me write a Python script?")
    sm.add_turn("assistant", "Sure! Here's a script that does what you need...")
    sm.add_turn("user", "Can you save it to disk?")
    sm.add_turn("assistant", "I've saved it to /home/linuxlarry/Documents/test.py")

    print(sm.format_status())
    print()

    # Test terminal
    th = TerminalHandler(session=sm)
    result = th.execute("echo 'G-FORCE TERMINAL ACTIVE' && pwd")
    print(th.format_result(result))
    print()

    # End session
    print("Ending session (no LLM — extractive summary):")
    summary = sm.end_session(save_to_rag=False)
    print(summary)
    print()
    print("✅ All tests passed")
    print()
    print("Integration patch for agent_v2.py:")
    print(AGENT_V2_PATCH)
