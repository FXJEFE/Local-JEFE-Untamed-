# Local Larry Agent — Personal Workspace Structure

This folder (`personal_ai_training`) is the **official home** for the agent as per user directive given on 28/05/2026.

## Required Directory Layout

```
personal_ai_training/
├── prompts/                    # All system prompts and custom instructions
│   └── LARRY_SYSTEM_PROMPT.md
├── conversations/              # Timestamped conversation logs & task records
│   └── 20250528_2346_Tasks_Persistence_Conversation.md
├── skills/                     # Reusable skills learned or created from tasks
├── tasks/                      # Records of executed tasks + outcomes
├── memory/                     # Long-term structured memory / handoff data
├── agent_sandbox/              # (Future) Strict sandbox for all file creation & command execution
└── README_AGENT_STRUCTURE.md
```

## Core Rules (Established 28-29 May 2026)

1. **All files/scripts the agent creates must go inside this folder** (or approved subfolders).
2. The agent must maintain real disk-based persistence (not just in-memory or VRAM).
3. Tasks should be converted into reusable skills over time.
4. Full auditability: timestamp everything important.

This structure supports the long-term goal of turning the Telegram bot into a truly personal, persistent, sandboxed agent.