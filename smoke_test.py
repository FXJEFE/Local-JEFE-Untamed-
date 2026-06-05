#!/usr/bin/env python3
"""
Larry G-Force Comprehensive Smoke Test
======================================
Tests core functionality: MCP, Tools, Model Router, Safe Executor, RAG, basic chat.

Run with:
    python smoke_test.py
    python smoke_test.py --quick
"""

import os
import sys
from pathlib import Path

# Bootstrap
try:
    import larry_paths
    larry_paths.bootstrap(chdir=True, add_to_sys_path=True)
except Exception:
    pass

PROJECT_ROOT = Path(__file__).parent.resolve()

def test_imports():
    print("[1] Testing imports...")
    from model_router import get_router
    from mcp_client import MCPClient
    from safe_code_executor import get_executor
    from web_tools import WebScraper
    from unified_context_manager import UnifiedContextManager
    print("    ✓ All critical imports successful")

def test_model_router():
    print("[2] Testing Model Router...")
    router = get_router()
    models = router.list_available()
    print(f"    ✓ Found {len(models)} models")
    if models:
        print(f"    ✓ Current model: {router.current_model}")

def test_mcp():
    print("[3] Testing MCP...")
    try:
        client = MCPClient()
        print(f"    ✓ MCPClient initialized. Servers: {len(getattr(client, 'servers', {}))}")
    except Exception as e:
        print(f"    ⚠ MCP test skipped or failed: {e}")

def test_safe_executor():
    print("[4] Testing Safe Code Executor...")
    executor = get_executor()
    result = executor.run("print('Hello from safe executor')", language="python")
    if result.get("success"):
        print("    ✓ Safe executor works")
    else:
        print(f"    ⚠ Safe executor returned: {result}")

def test_web_tools():
    print("[5] Testing Web Tools (light check)...")
    try:
        scraper = WebScraper()
        print("    ✓ WebScraper instantiated")
    except Exception as e:
        print(f"    ⚠ Web tools check: {e}")

def test_unified_context():
    print("[6] Testing Unified Context Manager...")
    try:
        ctx = UnifiedContextManager()
        ctx.save_conversation("smoke_test", [{"role": "user", "content": "test"}])
        print("    ✓ UnifiedContextManager basic write works")
    except Exception as e:
        print(f"    ⚠ Context manager: {e}")

def main():
    print("=== LARRY G-FORCE SMOKE TEST ===\n")
    test_imports()
    test_model_router()
    test_mcp()
    test_safe_executor()
    test_web_tools()
    test_unified_context()
    print("\n✅ Smoke test completed. Review any ⚠ warnings above.")

if __name__ == "__main__":
    main()
