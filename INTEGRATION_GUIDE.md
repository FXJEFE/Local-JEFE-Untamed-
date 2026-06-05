# Integration Guide: Updating Existing Files for Unified System

This document provides step-by-step instructions for integrating the unified context management system into your existing Local Larry codebase.

## Overview

The unified system introduces several architectural improvements:

1. **Centralized Context Management**: Single SQLite database replaces fragmented JSON storage
2. **Hardware Profile Management**: Persistent user preferences with intelligent auto-selection
3. **Sandbox Workflow**: Structured file editing with testing and approval gates
4. **Cross-Platform Compatibility**: Consistent path handling across Windows, Linux, and macOS
5. **Token Management**: Accurate token counting with tiktoken integration

## Phase 1: Update agent_v2.py

### Step 1.1: Update Imports

Replace the existing context management imports at the top of `agent_v2.py`:

```python
# OLD CODE (remove these lines):
# from context_manager import (
#     ContextManager,
#     ModelTaskManager,
#     get_context_manager,
#     get_task_manager,
# )

# NEW CODE (add these lines):
from unified_context_manager import UnifiedContextManager, get_context_manager
from hardware_profiles import ProfileManager, get_profile_manager
from sandbox_manager import SandboxManager, get_sandbox_manager
from cross_platform_paths import CrossPlatformPathManager, get_path_manager
from token_manager import get_token_manager
```

### Step 1.2: Update EnhancedAgent.__init__()

Locate the `__init__` method of the `EnhancedAgent` class and replace the context and profile initialization:

```python
def __init__(self, working_dir: str = None):
    # ... existing initialization code ...
    
    # OLD CODE (remove):
    # self.conversation = ConversationStore()
    # self.current_profile = "BALANCED"
    
    # NEW CODE (add):
    # Initialize unified context manager
    self.context = get_context_manager(
        db_path=str(BASE_DIR / "data" / "unified_context.db"),
        context_limit=65536  # Will be overridden by profile
    )
    
    # Initialize hardware profile manager
    self.profile_manager = get_profile_manager(
        db_path=str(BASE_DIR / "data" / "unified_context.db")
    )
    
    # Initialize sandbox manager
    self.sandbox = get_sandbox_manager(
        db_path=str(BASE_DIR / "data" / "unified_context.db"),
        sandbox_root=str(BASE_DIR / "sandbox")
    )
    
    # Initialize path manager
    self.path_manager = get_path_manager(str(BASE_DIR))
    
    # Initialize token manager
    self.token_manager = get_token_manager()
    
    # Create initial session
    self.session_id = self.context.create_session("cli")
    
    # Update context limit based on profile
    profile = self.profile_manager.get_profile()
    self.context.context_limit = profile.num_ctx
```

### Step 1.3: Update chat() Method

Replace the conversation management in the `chat()` method:

```python
def chat(self, user_input: str, task_type: TaskType = TaskType.GENERAL) -> str:
    """Enhanced chat with unified context management"""
    
    # Add user message to context
    status = self.context.add_message("user", user_input)
    
    if status['summarized']:
        logger.info("Context was automatically summarized")
    
    # Get profile for this task
    profile = self.profile_manager.get_profile(
        task_type=task_type.value,
        query_length=len(user_input)
    )
    
    # Get messages that fit in context
    messages = self.context.get_messages_for_prompt(
        max_tokens=profile.num_ctx - 1000,  # Reserve space for response
        include_summary=True
    )
    
    # Convert to Ollama format
    ollama_messages = [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]
    
    # Add system prompt if needed
    if not any(msg.role == "system" for msg in messages):
        ollama_messages.insert(0, {
            "role": "system",
            "content": self.get_system_prompt()
        })
    
    # Make request with profile options
    try:
        router = get_router()
        response = router.chat(
            messages=ollama_messages,
            task_type=task_type,
            options=profile.to_ollama_options()
        )
        
        # Store assistant response
        self.context.add_message("assistant", response)
        
        return response
        
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.error(error_msg)
        return error_msg
```

### Step 1.4: Add New CLI Commands

Add these new commands to the main CLI loop in `agent_v2.py`:

```python
# In the main loop, add these command handlers:

elif cmd == "profile":
    """Set or view hardware profile"""
    if not args:
        current = self.profile_manager.get_current_profile_name()
        profiles = self.profile_manager.get_available_profiles()
        
        print(f"\nCurrent Profile: {current}\n")
        print("Available Profiles:")
        print("=" * 60)
        for name, desc in profiles.items():
            details = self.profile_manager.get_profile_details(name)
            print(f"\n{name}:")
            print(f"  {desc}")
            print(f"  Context: {details['context_size']:,} tokens")
            print(f"  Memory: {details['memory_estimate']['total_estimate']}")
        
        print("\nUsage: /profile [SPEED|BALANCED|ACCURACY|ULTRA_CONTEXT|AUTO]")
    else:
        profile_name = args.upper().strip()
        if self.profile_manager.set_preference(profile_name):
            profile = self.profile_manager.get_profile()
            self.context.context_limit = profile.num_ctx
            print(f"✅ Profile set to: {profile_name}")
            print(f"   Context limit: {profile.num_ctx:,} tokens")
        else:
            print("❌ Invalid profile name")
    continue

elif cmd == "context":
    """Show context statistics"""
    stats = self.context.get_stats()
    print(f"\nContext Statistics:")
    print(f"  Session: {stats.session_id[:8]}...")
    print(f"  Messages: {stats.message_count}")
    print(f"  Tokens: {stats.total_tokens:,} / {stats.context_limit:,}")
    print(f"  Usage: {stats.usage_percent:.1f}%")
    print(f"  Summaries: {stats.summary_count}")
    
    if stats.is_near_limit():
        print(f"\n⚠️  Context approaching limit - summarization may occur")
    continue

elif cmd == "sessions":
    """List recent sessions"""
    sessions = self.context.list_sessions(interface="cli", limit=10)
    
    if not sessions:
        print("No previous sessions found")
    else:
        print("\nRecent Sessions:")
        print("=" * 80)
        for session in sessions:
            print(f"\nSession: {session['session_id'][:8]}...")
            print(f"  Created: {session['created_at']}")
            print(f"  Updated: {session['updated_at']}")
            print(f"  Messages: {session['message_count']}")
            print(f"  Tokens: {session['total_tokens']:,}")
    continue

elif cmd == "sandbox":
    """Show sandbox status"""
    status = self.sandbox.get_sandbox_status(self.session_id)
    
    if not status:
        print("📦 Sandbox is empty")
    else:
        print("\n📦 Sandbox Status:")
        print("=" * 80)
        for item in status:
            status_icon = "✅" if item['approved'] else "⚠️"
            test_icon = {
                'passed': '✓',
                'failed': '✗',
                'syntax_ok': '○',
                None: '·'
            }.get(item['test_status'], '?')
            
            file_name = Path(item['file_path']).name
            print(f"\n{status_icon} {file_name}")
            print(f"   Changed: {item['has_changes']}")
            print(f"   Tested: {test_icon}")
            print(f"   Time: {item['timestamp']}")
    continue

elif cmd == "stage":
    """Stage file for sandbox editing"""
    if not args:
        print("❌ Usage: /stage <file_path>")
        continue
    
    success, message = self.sandbox.stage_file(
        self.session_id,
        args.strip()
    )
    
    print("✅" if success else "❌", message)
    continue

elif cmd == "test":
    """Test sandbox file"""
    if not args:
        print("❌ Usage: /test <file_path>")
        continue
    
    print("🧪 Testing file...")
    success, results = self.sandbox.test_file(
        self.session_id,
        args.strip()
    )
    
    if success:
        print("✅ Tests passed")
    else:
        print("❌ Tests failed")
    
    print("\nResults:")
    print(json.dumps(results, indent=2))
    continue

elif cmd == "deploy":
    """Deploy sandbox changes"""
    if not args:
        print("❌ Usage: /deploy <file_path>")
        continue
    
    print("🚀 Deploying changes...")
    success, message = self.sandbox.approve_and_deploy(
        self.session_id,
        args.strip(),
        create_backup=True
    )
    
    print("✅" if success else "❌", message)
    continue

elif cmd == "discard":
    """Discard sandbox changes"""
    if not args:
        print("❌ Usage: /discard <file_path>")
        continue
    
    success, message = self.sandbox.discard_changes(
        self.session_id,
        args.strip()
    )
    
    print("✅" if success else "❌", message)
    continue
```

## Phase 2: Update telegram_bot.py

### Step 2.1: Update Imports

Add these imports at the top of `telegram_bot.py`:

```python
from unified_context_manager import UnifiedContextManager, get_context_manager
from hardware_profiles import ProfileManager, get_profile_manager
from sandbox_manager import SandboxManager, get_sandbox_manager
```

### Step 2.2: Update TelegramBot.__init__()

Modify the initialization to use unified context:

```python
def __init__(self, token: str, allowed_chat_ids: List[int]):
    # ... existing initialization ...
    
    # NEW: Initialize unified managers
    self.context_manager = get_context_manager()
    self.profile_manager = get_profile_manager()
    self.sandbox_manager = get_sandbox_manager()
    
    # Track sessions per chat
    self.chat_sessions: Dict[int, str] = {}
```

### Step 2.3: Update get_conversation() Method

Replace conversation context handling:

```python
def get_conversation(self, chat_id: int) -> str:
    """Get or create session for chat"""
    if chat_id not in self.chat_sessions:
        # Create new session
        session_id = self.context_manager.create_session(
            interface="telegram",
            chat_id=chat_id
        )
        self.chat_sessions[chat_id] = session_id
        
        # Load profile
        profile = self.profile_manager.get_profile()
        self.context_manager.context_limit = profile.num_ctx
    else:
        # Load existing session
        session_id = self.chat_sessions[chat_id]
        self.context_manager.load_session(session_id)
    
    return session_id
```

### Step 2.4: Add New Bot Commands

Add these command methods to the `TelegramBot` class:

```python
def cmd_profile(self, chat_id: int, args: str) -> str:
    """Switch hardware utilization profiles"""
    if not args:
        current = self.profile_manager.get_current_profile_name()
        profiles = self.profile_manager.get_available_profiles()
        
        profile_list = "\n".join([
            f"• `{name}`: {desc}"
            for name, desc in profiles.items()
        ])
        
        return (
            f"**Current Profile:** `{current}`\n\n"
            f"**Available Profiles:**\n{profile_list}\n\n"
            f"**AUTO Mode:** Let the system choose based on task\n\n"
            f"**Usage:** `/profile ACCURACY` or `/profile AUTO`"
        )
    
    new_profile = args.upper().strip()
    
    if new_profile not in ["SPEED", "BALANCED", "ACCURACY", "ULTRA_CONTEXT", "AUTO"]:
        return "❌ Invalid profile. Use: SPEED, BALANCED, ACCURACY, ULTRA_CONTEXT, or AUTO"
    
    if self.profile_manager.set_preference(new_profile):
        profile = self.profile_manager.get_profile()
        self.context_manager.context_limit = profile.num_ctx
        
        mode_desc = "automatic selection" if new_profile == "AUTO" else new_profile
        return f"✅ **Profile Set:** {mode_desc}\n\nContext: {profile.num_ctx:,} tokens"
    else:
        return "❌ Failed to save profile preference"

def cmd_context(self, chat_id: int, args: str) -> str:
    """Show context usage statistics"""
    session_id = self.get_conversation(chat_id)
    stats = self.context_manager.get_stats()
    
    return (
        f"📊 **Context Statistics**\n\n"
        f"Session: `{stats.session_id[:8]}...`\n"
        f"Messages: {stats.message_count}\n"
        f"Tokens: {stats.total_tokens:,} / {stats.context_limit:,}\n"
        f"Usage: {stats.usage_percent:.1f}%\n"
        f"Summaries: {stats.summary_count}\n"
    )

def cmd_sandbox(self, chat_id: int, args: str) -> str:
    """Show sandbox status"""
    session_id = self.get_conversation(chat_id)
    status = self.sandbox_manager.get_sandbox_status(session_id)
    
    if not status:
        return "📦 Sandbox is empty\n\nUse `/stage <file>` to begin editing"
    
    output = ["📦 **Sandbox Status**\n"]
    
    for item in status:
        file_name = Path(item['file_path']).name
        status_icon = "✅" if item['approved'] else "⚠️"
        test_status = item['test_status'] or 'not_tested'
        
        output.append(f"{status_icon} `{file_name}`")
        output.append(f" • Modified: {item['has_changes']}")
        output.append(f" • Tests: {test_status}")
        output.append("")
    
    output.append("**Commands:**")
    output.append("`/stage <file>` - Stage file for editing")
    output.append("`/test <file>` - Run tests")
    output.append("`/deploy <file>` - Deploy to production")
    
    return "\n".join(output)

def cmd_stage(self, chat_id: int, args: str) -> str:
    """Stage file for sandbox editing"""
    if not args:
        return "❌ Usage: `/stage <file_path>`"
    
    session_id = self.get_conversation(chat_id)
    
    success, message = self.sandbox_manager.stage_file(
        session_id,
        args.strip()
    )
    
    if success:
        return f"✅ {message}\n\nFile is ready for editing."
    else:
        return f"❌ {message}"

def cmd_test(self, chat_id: int, args: str) -> str:
    """Test sandbox file"""
    if not args:
        return "❌ Usage: `/test <file_path>`"
    
    session_id = self.get_conversation(chat_id)
    self.send_typing(chat_id)
    
    success, results = self.sandbox_manager.test_file(
        session_id,
        args.strip()
    )
    
    output = ["🧪 **Test Results**\n"]
    
    if success:
        output.append("✅ All tests passed")
    else:
        output.append("❌ Tests failed")
    
    if 'static_analysis' in results:
        analysis = results['static_analysis']
        if analysis.get('valid_syntax'):
            output.append(f"\n✓ Valid Python syntax")
            output.append(f"• Functions: {len(analysis.get('functions', []))}")
            output.append(f"• Classes: {len(analysis.get('classes', []))}")
            output.append(f"• Complexity: {analysis.get('complexity', 0)}")
        else:
            output.append(f"\n✗ Syntax Error:")
            output.append(f"```\n{analysis.get('error', 'Unknown')}\n```")
    
    if 'execution' in results:
        exec_result = results['execution']
        if exec_result.get('success'):
            output.append("\n✓ Execution successful")
            if exec_result.get('stdout'):
                output.append(f"\n**Output:**\n```\n{exec_result['stdout'][:500]}\n```")
        else:
            output.append("\n✗ Execution failed")
            if exec_result.get('stderr'):
                output.append(f"\n**Error:**\n```\n{exec_result['stderr'][:500]}\n```")
    
    return "\n".join(output)

def cmd_deploy(self, chat_id: int, args: str) -> str:
    """Deploy sandbox changes to production"""
    if not args:
        return "❌ Usage: `/deploy <file_path>`"
    
    session_id = self.get_conversation(chat_id)
    self.send_typing(chat_id)
    
    success, message = self.sandbox_manager.approve_and_deploy(
        session_id,
        args.strip(),
        create_backup=True
    )
    
    if success:
        return f"🚀 **Deployed!**\n\n{message}\n\n✓ Backup created\n✓ Changes applied"
    else:
        return f"❌ **Deployment Failed**\n\n{message}"
```

### Step 2.5: Register New Commands

Update the command dictionary in `__init__()`:

```python
self.commands = {
    # ... existing commands ...
    "/profile": self.cmd_profile,
    "/context": self.cmd_context,
    "/sandbox": self.cmd_sandbox,
    "/stage": self.cmd_stage,
    "/test": self.cmd_test,
    "/deploy": self.cmd_deploy,
    "/discard": lambda chat_id, args: self.cmd_discard(chat_id, args),
}
```

## Phase 3: Update model_router.py

### Step 3.1: Integrate Profile Manager

Add profile manager integration to the `ModelRouter` class:

```python
from hardware_profiles import get_profile_manager

class ModelRouter:
    def __init__(self):
        # ... existing initialization ...
        self.profile_manager = get_profile_manager()
    
    def chat(
        self,
        messages: List[Dict],
        task_type: TaskType = TaskType.GENERAL,
        options: Optional[Dict] = None
    ) -> str:
        """Enhanced chat with profile integration"""
        
        # Get profile if options not explicitly provided
        if options is None:
            profile = self.profile_manager.get_profile(task_type=task_type.value)
            options = profile.to_ollama_options()
        
        # ... rest of existing chat implementation ...
```

## Phase 4: Integration Checklist

Use this checklist to verify your integration is complete:

- [ ] All new Python files are in project root
- [ ] Database schema is initialized (run setup_unified.py)
- [ ] agent_v2.py imports updated
- [ ] agent_v2.py __init__ updated with new managers
- [ ] agent_v2.py chat() method updated
- [ ] agent_v2.py CLI commands added
- [ ] telegram_bot.py imports updated
- [ ] telegram_bot.py __init__ updated
- [ ] telegram_bot.py commands added
- [ ] model_router.py profile integration added
- [ ] .env file created and configured
- [ ] requirements-production.txt updated
- [ ] All tests pass (run pytest tests/)

## Phase 5: Testing

After integration, test these workflows:

1. **Context Persistence**: Start CLI session, chat, exit. Restart and verify history restored.
2. **Profile Switching**: Change profiles, verify context limits update.
3. **Sandbox Workflow**: Stage file, edit, test, deploy. Verify backup created.
4. **Cross-Platform Paths**: Test on Windows and Linux. Verify paths normalize correctly.
5. **Token Management**: Send long messages. Verify automatic summarization triggers.
6. **Telegram Integration**: Send messages via Telegram. Verify shared context with CLI.

## Phase 6: Migration from Old System

If you have existing conversation history:

```python
import json
from pathlib import Path
from unified_context_manager import get_context_manager

# Load old history
old_history = json.loads(Path("data/conversation_history.json").read_text())

# Create context manager
context = get_context_manager()
session_id = context.create_session("migrated")

# Migrate messages
for msg in old_history:
    context.add_message(
        role=msg["role"],
        content=msg["content"]
    )

print(f"Migrated {len(old_history)} messages to session {session_id}")
```

## Troubleshooting

### Issue: "No module named 'unified_context_manager'"

**Solution**: Ensure all new Python files are in your project root directory alongside agent_v2.py.

### Issue: "Database is locked"

**Solution**: Close all instances of the agent before starting a new one. SQLite doesn't support concurrent writes well.

### Issue: "Context not persisting"

**Solution**: Verify the database file has write permissions:
```bash
chmod 644 data/unified_context.db
```

### Issue: "Sandbox tests failing"

**Solution**: Ensure SafeCodeExecutor is available and test_file() has access to it.

## Next Steps

After completing the integration:

1. Review the Implementation Roadmap for advanced features
2. Configure HashiCorp Vault for production secrets management
3. Set up automated backups of the unified database
4. Configure monitoring and logging
5. Review security considerations in README_UPDATED.md

## Support

For integration issues:
- Check logs in ./logs/larry.log
- Review database schema in data/unified_context.db
- Test individual components with their __main__ blocks
- Consult README_UPDATED.md for detailed documentation
