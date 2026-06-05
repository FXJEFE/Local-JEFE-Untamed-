#!/usr/bin/env python3
"""
Complete A-Z Test Workflow for LarryLinux Agent
Tests all components: MCP, RAG, Models, File Ops, etc.
"""

import asyncio
import sys
import os

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🧪 LarryLinux Agent - Complete A-Z Test Workflow")
print("=" * 70)

# Track test results
results = {"passed": 0, "failed": 0, "skipped": 0}

def test(name, condition, details=""):
    """Simple test reporter"""
    global results
    if condition:
        results["passed"] += 1
        print(f"✅ {name}")
        if details:
            print(f"   {details}")
    else:
        results["failed"] += 1
        print(f"❌ {name}")
        if details:
            print(f"   {details}")

def skip(name, reason=""):
    """Skip a test"""
    global results
    results["skipped"] += 1
    print(f"⏭️  {name} - SKIPPED" + (f" ({reason})" if reason else ""))

# ============================================================
# TEST 1: Core Imports
# ============================================================
print("\n" + "=" * 70)
print("📦 TEST 1: Core Imports")
print("=" * 70)

try:
    from model_router import ModelRouter
    test("ModelRouter import", True)
except Exception as e:
    test("ModelRouter import", False, str(e))

try:
    from context_manager import ContextManager
    test("ContextManager import", True)
except Exception as e:
    test("ContextManager import", False, str(e))

try:
    from vector_enhanced import EnhancedRAG, ChromaDBVectorStore
    test("VectorEnhanced import", True)
except Exception as e:
    test("VectorEnhanced import", False, str(e))

try:
    from mcp_client import get_mcp_toolkit, MCPToolkit
    test("MCP Client import", True)
except Exception as e:
    test("MCP Client import", False, str(e))

try:
    from web_tools import WebScraper, YouTubeSummarizer
    test("WebTools import", True)
except Exception as e:
    test("WebTools import", False, str(e))

# ============================================================
# TEST 2: MCP Native Servers
# ============================================================
print("\n" + "=" * 70)
print("🔌 TEST 2: MCP Native Servers")
print("=" * 70)

try:
    mcp = get_mcp_toolkit()
    test("MCPToolkit initialization", mcp is not None)
    
    # Test each server
    test("GitHub Tools", mcp.github is not None, 
         f"User: {mcp.github.get_user().get('login', 'N/A')}" if mcp.github else "Not configured")
    
    test("Filesystem Tools", mcp.filesystem is not None)
    test("Memory Tools", mcp.memory is not None)
    test("SQLite Tools", mcp.sqlite is not None)
    test("Brave Search Tools", mcp.brave_search is not None)
    
    # Test GitHub repos
    if mcp.github:
        repos = mcp.github.list_repos()[:3]
        test("GitHub API - List Repos", len(repos) > 0, 
             f"Found {len(repos)} repos, first: {repos[0].get('name', 'N/A')}" if repos else "No repos")
    
    # Test Filesystem
    if mcp.filesystem:
        files = mcp.filesystem.list_directory(".")
        test("Filesystem - List Directory", len(files) > 0, f"Found {len(files)} items")
    
    # Test Memory (Knowledge Graph)
    if mcp.memory:
        # Add a test entity
        result = mcp.memory.create_entities([{
            "name": "test_entity_workflow",
            "entityType": "test",
            "observations": ["Created during A-Z test workflow"]
        }])
        test("Memory - Create Entity", len(result.get("created", [])) > 0)
        
        # Search for it
        found = mcp.memory.search_nodes("test_entity_workflow")
        test("Memory - Search Nodes", len(found) > 0)
        
        # Clean up
        mcp.memory.delete_entities(["test_entity_workflow"])
        test("Memory - Delete Entity", True)
    
    # Test SQLite
    if mcp.sqlite:
        # Create test table
        mcp.sqlite.execute("CREATE TABLE IF NOT EXISTS test_workflow (id INTEGER PRIMARY KEY, name TEXT)")
        mcp.sqlite.execute("INSERT INTO test_workflow (name) VALUES ('test_item')")
        result = mcp.sqlite.query("SELECT * FROM test_workflow WHERE name = 'test_item'")
        test("SQLite - CRUD Operations", len(result) > 0)
        mcp.sqlite.execute("DROP TABLE test_workflow")
        test("SQLite - Cleanup", True)
    
    # Test Brave Search (only if configured)
    if mcp.brave_search:
        try:
            results_search = mcp.brave_search.web_search("Python programming", count=3)
            test("Brave Search - Web Search", len(results_search) > 0, 
                 f"Found {len(results_search)} results")
        except Exception as e:
            test("Brave Search - Web Search", False, str(e))
    
except Exception as e:
    test("MCP Native Servers", False, str(e))
    import traceback
    traceback.print_exc()

# ============================================================
# TEST 3: Model Router
# ============================================================
print("\n" + "=" * 70)
print("🤖 TEST 3: Model Router")
print("=" * 70)

try:
    router = ModelRouter()
    
    # Check models
    models = router.available_models
    test("Ollama Models Available", len(models) > 0, f"Found {len(models)} models")
    
    # Test routing
    code_model = router.route_query("Write a Python function to sort a list")[0]
    test("Route: Code Task", code_model is not None, f"Selected: {code_model}")
    
    chat_model = router.route_query("Hello, how are you?")[0]
    test("Route: Chat Task", chat_model is not None, f"Selected: {chat_model}")
    
    math_model = router.route_query("Calculate the derivative of x^2 + 3x")[0]
    test("Route: Math Task", math_model is not None, f"Selected: {math_model}")
    
except Exception as e:
    test("Model Router", False, str(e))

# ============================================================
# TEST 4: Context Manager
# ============================================================
print("\n" + "=" * 70)
print("📝 TEST 4: Context Manager")
print("=" * 70)

try:
    from context_manager import get_context_manager
    cm = get_context_manager(router)
    
    # Add messages
    cm.add_message("user", "Hello, this is a test message")
    cm.add_message("assistant", "Hello! I'm here to help with your test.")
    
    stats = cm.get_stats()
    test("Context - Add Messages", stats["message_count"] >= 2)
    
    # Get context string
    context = cm.get_context_for_prompt()
    test("Context - Get Context", len(context) > 0)
    
    # Check token estimation
    tokens = stats["current_tokens"]
    test("Context - Token Estimation", tokens > 0, f"Current {tokens} tokens")
    
    # Clear (new session)
    cm.new_session()
    stats = cm.get_stats()
    test("Context - Clear", stats["message_count"] == 0)
    
except Exception as e:
    test("Context Manager", False, str(e))

# ============================================================
# TEST 5: Vector/RAG System
# ============================================================
print("\n" + "=" * 70)
print("🧠 TEST 5: Vector/RAG System")
print("=" * 70)

try:
    # Initialize with test directory
    rag = EnhancedRAG(persist_directory="./test_chroma_db")
    test("EnhancedRAG Init", rag is not None)
    
    # Add test document
    test_doc = "This is a test document about Python programming and machine learning."
    rag.add_document(test_doc, metadata={"source": "test_workflow"})
    test("RAG - Add Document", True)
    
    # Search
    results_rag = rag.search("Python programming", k=3)
    test("RAG - Search", len(results_rag) > 0, f"Found {len(results_rag)} results")
    
    # Check if rag is working
    test("RAG - System Ready", rag.client is not None, "ChromaDB initialized")
    
except Exception as e:
    test("Vector/RAG System", False, str(e))

# ============================================================
# TEST 6: Web Tools
# ============================================================
print("\n" + "=" * 70)
print("🌐 TEST 6: Web Tools")
print("=" * 70)

try:
    ws = WebScraper()
    test("WebScraper Init", ws is not None)
    
    # Test scraping (simple)
    try:
        content = ws.fetch_url("https://httpbin.org/html")
        test("WebScraper - Fetch URL", len(content) > 0, f"Got {len(content)} chars")
    except Exception as e:
        skip("WebScraper - Fetch URL", f"Network issue: {e}")
    
except Exception as e:
    test("Web Tools", False, str(e))

# ============================================================
# TEST 7: File Operations
# ============================================================
print("\n" + "=" * 70)
print("📁 TEST 7: File Operations")
print("=" * 70)

try:
    import tempfile
    import shutil
    
    # Create temp directory
    test_dir = tempfile.mkdtemp(prefix="larrylinux_test_")
    test("File Ops - Create Temp Dir", os.path.exists(test_dir))
    
    # Write file
    test_file = os.path.join(test_dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("Hello, LarryLinux!")
    test("File Ops - Write File", os.path.exists(test_file))
    
    # Read file
    with open(test_file, "r") as f:
        content = f.read()
    test("File Ops - Read File", content == "Hello, LarryLinux!")
    
    # Cleanup
    shutil.rmtree(test_dir)
    test("File Ops - Cleanup", not os.path.exists(test_dir))
    
except Exception as e:
    test("File Operations", False, str(e))

# ============================================================
# TEST 8: Agent Integration (Quick)
# ============================================================
print("\n" + "=" * 70)
print("🚀 TEST 8: Agent Integration")
print("=" * 70)

try:
    # Import the full agent
    from agent_v2 import EnhancedAgent
    test("EnhancedAgent Import", True)
    
    # Initialize (this is the full integration test)
    agent = EnhancedAgent()
    test("EnhancedAgent Init", agent is not None)
    
    # Check components
    test("Agent - Model Router", agent.router is not None)
    test("Agent - Context Manager", agent.context_mgr is not None)
    test("Agent - RAG System", agent.rag_manager is not None)
    test("Agent - MCP Tools", agent.mcp is not None)
    
    # Check available tools
    tools = agent.mcp.get_available_tools() if agent.mcp else []
    test("Agent - MCP Tools List", len(tools) > 0, f"Tools: {tools}")
    
except Exception as e:
    test("Agent Integration", False, str(e))
    import traceback
    traceback.print_exc()

# ============================================================
# RESULTS SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("📊 TEST RESULTS SUMMARY")
print("=" * 70)
total = results["passed"] + results["failed"] + results["skipped"]
print(f"  ✅ Passed:  {results['passed']}/{total}")
print(f"  ❌ Failed:  {results['failed']}/{total}")
print(f"  ⏭️  Skipped: {results['skipped']}/{total}")
print("=" * 70)

if results["failed"] == 0:
    print("🎉 ALL TESTS PASSED! LarryLinux is ready to use.")
else:
    print(f"⚠️  {results['failed']} test(s) failed. Check the output above.")

sys.exit(0 if results["failed"] == 0 else 1)
