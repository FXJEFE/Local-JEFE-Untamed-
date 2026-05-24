#!/usr/bin/env python3
"""
MCP Client - Native Python Implementation
No Docker required - uses local MCP servers and direct APIs
"""

import json
import logging
import os
import sys
import requests
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure the project root (containing mcp_servers/ package) is importable
try:
    from larry_paths import BASE_DIR
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
except Exception:
    pass

# Import native MCP servers (optional - the full mcp_servers package is not present in this clean distribution)
try:
    from mcp_servers import (
        FilesystemServer, MemoryServer, SQLiteServer,
        BraveSearchServer, Context7Server, PlaywrightServer,
        N8NServer, PodmanServer, registry
    )
    NATIVE_SERVERS_AVAILABLE = True
except ImportError:
    NATIVE_SERVERS_AVAILABLE = False
    logger.info("Native in-process mcp_servers package not found (this is normal for the FXJEFE distribution). External MCP servers will be used instead.")


@dataclass
class MCPConfig:
    """MCP configuration from JSON."""
    github_token: Optional[str] = None
    brave_api_key: Optional[str] = None
    allowed_paths: List[str] = None
    memory_path: str = "memory.json"
    sqlite_path: str = "database.db"


class MCPClient:
    """Client for managing native MCP servers."""
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            try:
                from larry_paths import MCP_CONFIG_FILE
                self.config_path = MCP_CONFIG_FILE
            except Exception:
                self.config_path = Path("mcp.json")
        else:
            self.config_path = Path(config_path)
        self.config = MCPConfig()
        self.servers = {}
        self._load_config()
        self._init_servers()
    
    def _load_config(self):
        """Load configuration from JSON and environment."""
        # Load from mcp.json
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    data = json.load(f)
                
                # Handle new format with 'servers' key or old array format
                if isinstance(data, dict) and "servers" in data:
                    configs = data["servers"]
                elif isinstance(data, list):
                    configs = data
                else:
                    logger.warning("Unknown mcp.json format")
                    configs = []
                
                for cfg in configs:
                    name = cfg.get("name", "")
                    params = cfg.get("params", {})
                    env = params.get("env", {})

                    # FIXED: mcp.json uses api_key_env (the NAME of an env var),
                    # not a literal token value — resolve it from the environment.
                    def _resolve_key(p, field):
                        env_var_name = p.get(field, "")
                        return os.environ.get(env_var_name, "") if env_var_name else ""

                    if name == "github":
                        token = (
                            _resolve_key(params, "api_key_env")
                            or env.get("GITHUB_TOKEN", "")
                        )
                        if token:
                            self.config.github_token = token
                            logger.info("✅ Loaded GitHub token from env")

                    if name == "brave-search":
                        key = (
                            _resolve_key(params, "api_key_env")
                            or params.get("headers", {}).get("X-Subscription-Token", "")
                        )
                        if key:
                            self.config.brave_api_key = key
                            logger.info("✅ Loaded Brave Search API key from env")

                    if name == "filesystem":
                        sandbox = params.get("sandbox_root", env.get("SANDBOX_ROOT", "."))
                        self.config.allowed_paths = [
                            sandbox,
                            str(Path.cwd()),
                            str(Path(__file__).parent),
                        ]

                    if name == "sqlite":
                        self.config.sqlite_path = params.get("db_path", env.get("DB_PATH", "database.db"))

                    if name == "memory":
                        self.config.memory_path = params.get("storage_path", env.get("STORAGE_PATH", "memory.json"))
                        
            except Exception as e:
                logger.warning(f"Error loading mcp.json: {e}")
        
        # Override from environment
        self.config.github_token = os.environ.get("GITHUB_TOKEN", self.config.github_token)
        self.config.brave_api_key = os.environ.get("BRAVE_API_KEY", self.config.brave_api_key)
    
    def _init_servers(self):
        """Initialize native MCP servers."""
        if not NATIVE_SERVERS_AVAILABLE:
            logger.warning("Native servers not available")
            return

        # Import lazily via the registry so missing optional deps don't crash
        # the whole init. Each server is tried in isolation.
        try:
            from mcp_servers import registry as _mcp_registry
        except Exception as e:
            logger.warning(f"mcp_servers registry unavailable: {e}")
            _mcp_registry = {}

        # Initialize time server (no config required) — optional.
        if "time" in _mcp_registry:
            try:
                self.servers["time"] = _mcp_registry["time"]()
                logger.info("✅ Time server ready")
            except Exception as e:
                logger.warning(f"Time server failed: {e}")

        # Initialize filesystem server
        try:
            allowed = self.config.allowed_paths or [str(Path.cwd())]
            self.servers["filesystem"] = FilesystemServer(allowed)
            logger.info("âœ… Filesystem server ready")
        except Exception as e:
            logger.warning(f"Filesystem server failed: {e}")
        
        # Initialize memory server
        try:
            self.servers["memory"] = MemoryServer(self.config.memory_path)
            logger.info("âœ… Memory server ready")
        except Exception as e:
            logger.warning(f"Memory server failed: {e}")
        
        # Initialize SQLite server
        try:
            self.servers["sqlite"] = SQLiteServer(self.config.sqlite_path)
            logger.info("âœ… SQLite server ready")
        except Exception as e:
            logger.warning(f"SQLite server failed: {e}")
        
        # Initialize Brave Search if API key available
        if self.config.brave_api_key:
            try:
                self.servers["brave-search"] = BraveSearchServer(self.config.brave_api_key)
                logger.info("âœ… Brave Search server ready")
            except Exception as e:
                logger.warning(f"Brave Search server failed: {e}")

        # Initialize Context7 server
        try:
            self.servers["context7"] = Context7Server()
            logger.info("âœ… Context7 server ready")
        except Exception as e:
            logger.warning(f"Context7 server failed: {e}")

        # Initialize Playwright server
        try:
            self.servers["playwright"] = PlaywrightServer(headless=True)
            logger.info("âœ… Playwright server ready")
        except Exception as e:
            logger.warning(f"Playwright server failed: {e}")

        # Initialize n8n server
        try:
            n8n_url = os.getenv("N8N_URL", "http://localhost:5678")
            n8n_api_key = os.getenv("N8N_API_KEY", "")
            self.servers["n8n"] = N8NServer(base_url=n8n_url, api_key=n8n_api_key)
            logger.info("âœ… n8n server ready")
        except Exception as e:
            logger.warning(f"n8n server failed: {e}")
        
        # Initialize Podman/Docker server
        try:
            self.servers["podman"] = PodmanServer()
            logger.info(" Podman server ready")
        except Exception as e:
            logger.warning(f"Podman server failed: {e}")
    
    def call(self, server_name: str, method: str, params: Dict = None) -> Dict:
        """Call a method on a native MCP server."""
        if server_name not in self.servers:
            return {"error": f"Server not found: {server_name}"}
        
        srv = self.servers[server_name]
        if isinstance(srv, str):
            return {"error": f"Server '{server_name}' is not properly initialized (got str)"}
        try:
            response = srv.call(method, params or {})
            return response.result if getattr(response, 'success', False) else {"error": getattr(response, 'error', 'unknown')}
        except Exception as e:
            return {"error": f"Server call failed: {e}"}
    
    def is_available(self, server_name: str) -> bool:
        """Check if a server is available."""
        if server_name == "github":
            return bool(self.config.github_token)
        srv = self.servers.get(server_name)
        return srv is not None and not isinstance(srv, str)

    @property
    def native_servers_available(self) -> bool:
        return NATIVE_SERVERS_AVAILABLE

    def status(self) -> Dict:
        return {
            "native_servers_available": NATIVE_SERVERS_AVAILABLE,
            "initialized_servers": list(self.servers.keys()),
            "github_token_loaded": bool(self.config.github_token),
            "brave_key_loaded": bool(self.config.brave_api_key),
        }


class GitHubTools:
    """GitHub API Tools - Direct REST API calls."""
    
    TOOLS = [
        ("get_user", "Get authenticated user info"),
        ("list_repos", "List repositories for user"),
        ("get_repo", "Get repository details"),
        ("list_issues", "List issues in a repository"),
        ("create_issue", "Create a new issue"),
        ("get_file_contents", "Get file contents from repo"),
        ("search_code", "Search code in GitHub"),
        ("list_pull_requests", "List pull requests"),
        ("create_pull_request", "Create a pull request"),
    ]
    
    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client
        self.base_url = "https://api.github.com"
        self.headers = {}
        if mcp_client.config.github_token:
            self.headers = {
                "Authorization": f"token {mcp_client.config.github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "LarryLinux-Agent"
            }
    
    @property
    def available(self) -> bool:
        return self.mcp.config.github_token is not None
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]
    
    def _request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None) -> Any:
        """Make a GitHub API request."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=self.headers, params=params, timeout=30)
            elif method == "POST":
                resp = requests.post(url, headers=self.headers, json=data, timeout=30)
            elif method == "PATCH":
                resp = requests.patch(url, headers=self.headers, json=data, timeout=30)
            else:
                return {"error": f"Unsupported method: {method}"}
            
            if resp.status_code >= 400:
                return {"error": f"GitHub API error {resp.status_code}: {resp.text[:200]}"}
            
            return resp.json() if resp.text else {"success": True}
        except requests.RequestException as e:
            return {"error": f"Request failed: {e}"}
    
    def _parse_repo(self, repo_string: str) -> tuple:
        """Parse 'owner/repo' format."""
        if "/" in repo_string:
            parts = repo_string.split("/", 1)
            return parts[0], parts[1]
        return None, repo_string
    
    def list_repos(self, owner: str = None) -> List[Dict]:
        """List repositories."""
        if owner:
            result = self._request("GET", f"/users/{owner}/repos", {"per_page": 100, "sort": "updated"})
        else:
            result = self._request("GET", "/user/repos", {"per_page": 100, "sort": "updated"})
        return result if isinstance(result, list) else []
    
    def get_repo(self, repo_string: str) -> Dict:
        """Get repository details."""
        owner, repo = self._parse_repo(repo_string)
        if not owner:
            return {"error": "Please use 'owner/repo' format"}
        return self._request("GET", f"/repos/{owner}/{repo}")
    
    def list_issues(self, repo_string: str, state: str = "open") -> List[Dict]:
        """List issues."""
        owner, repo = self._parse_repo(repo_string)
        if not owner:
            return {"error": "Please use 'owner/repo' format"}
        result = self._request("GET", f"/repos/{owner}/{repo}/issues", {"state": state, "per_page": 50})
        return result if isinstance(result, list) else []
    
    def create_issue(self, repo_string: str, title: str, body: str = "") -> Dict:
        """Create an issue."""
        owner, repo = self._parse_repo(repo_string)
        if not owner:
            return {"error": "Please use 'owner/repo' format"}
        return self._request("POST", f"/repos/{owner}/{repo}/issues", data={"title": title, "body": body})
    
    def get_file_contents(self, repo_string: str, path: str, ref: str = "main") -> Dict:
        """Get file contents from a repository."""
        owner, repo = self._parse_repo(repo_string)
        if not owner:
            return {"error": "Please use 'owner/repo' format"}
        return self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", {"ref": ref})
    
    def search_code(self, query: str, owner: str = None, repo: str = None) -> List[Dict]:
        """Search code in GitHub."""
        q = query
        if owner and repo:
            q = f"{query} repo:{owner}/{repo}"
        elif owner:
            q = f"{query} user:{owner}"
        result = self._request("GET", "/search/code", {"q": q, "per_page": 30})
        return result.get("items", []) if isinstance(result, dict) else []
    
    def list_pull_requests(self, repo_string: str, state: str = "open") -> List[Dict]:
        """List pull requests."""
        owner, repo = self._parse_repo(repo_string)
        if not owner:
            return {"error": "Please use 'owner/repo' format"}
        result = self._request("GET", f"/repos/{owner}/{repo}/pulls", {"state": state, "per_page": 50})
        return result if isinstance(result, list) else []
    
    def create_pull_request(self, repo_string: str, title: str, 
                           head: str, base: str = "main", body: str = "") -> Dict:
        """Create a pull request."""
        owner, repo = self._parse_repo(repo_string)
        if not owner:
            return {"error": "Please use 'owner/repo' format"}
        return self._request("POST", f"/repos/{owner}/{repo}/pulls", 
                           data={"title": title, "head": head, "base": base, "body": body})
    
    def get_user(self) -> Dict:
        """Get authenticated user."""
        return self._request("GET", "/user")


class FilesystemTools:
    """Filesystem tools using native MCP server."""
    
    TOOLS = [
        ("read_file", "Read file contents"),
        ("write_file", "Write content to file"),
        ("list_directory", "List directory contents"),
        ("search_files", "Search files by pattern"),
        ("file_info", "Get file metadata"),
    ]
    
    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client
    
    @property
    def available(self) -> bool:
        return self.mcp.is_available("filesystem")
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]
    
    def read_file(self, path: str) -> Dict:
        return self.mcp.call("filesystem", "read_file", {"path": path})
    
    def write_file(self, path: str, content: str) -> Dict:
        return self.mcp.call("filesystem", "write_file", {"path": path, "content": content})
    
    def list_directory(self, path: str = ".") -> Dict:
        return self.mcp.call("filesystem", "list_directory", {"path": path})
    
    def search_files(self, pattern: str, path: str = ".") -> Dict:
        return self.mcp.call("filesystem", "search_files", {"pattern": pattern, "path": path})
    
    def file_info(self, path: str) -> Dict:
        return self.mcp.call("filesystem", "file_info", {"path": path})


class MemoryTools:
    """Memory/Knowledge Graph tools using native MCP server."""
    
    TOOLS = [
        ("create_entities", "Create entities in knowledge graph"),
        ("create_relations", "Create relations between entities"),
        ("add_observations", "Add observations to entities"),
        ("search_nodes", "Search nodes in graph"),
        ("read_graph", "Read entire knowledge graph"),
        ("get_entity", "Get entity by name"),
    ]
    
    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client
    
    @property
    def available(self) -> bool:
        return self.mcp.is_available("memory")
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]
    
    def create_entities(self, entities: List[Dict]) -> Dict:
        return self.mcp.call("memory", "create_entities", {"entities": entities})
    
    def create_relations(self, relations: List[Dict]) -> Dict:
        return self.mcp.call("memory", "create_relations", {"relations": relations})
    
    def add_observations(self, observations: List[Dict]) -> Dict:
        return self.mcp.call("memory", "add_observations", {"observations": observations})
    
    def search_nodes(self, query: str) -> Dict:
        return self.mcp.call("memory", "search_nodes", {"query": query})
    
    def read_graph(self) -> Dict:
        return self.mcp.call("memory", "read_graph", {})
    
    def get_entity(self, name: str) -> Dict:
        return self.mcp.call("memory", "get_entity", {"name": name})


class SQLiteTools:
    """SQLite tools using native MCP server."""
    
    TOOLS = [
        ("query", "Execute SELECT query"),
        ("execute", "Execute SQL statement"),
        ("list_tables", "List database tables"),
        ("describe_table", "Get table schema"),
        ("insert", "Insert data into table"),
    ]
    
    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client
    
    @property
    def available(self) -> bool:
        return self.mcp.is_available("sqlite")
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]
    
    def query(self, sql: str, params: List = None) -> Dict:
        return self.mcp.call("sqlite", "query", {"sql": sql, "params": params})
    
    def execute(self, sql: str, params: List = None) -> Dict:
        return self.mcp.call("sqlite", "execute", {"sql": sql, "params": params})
    
    def list_tables(self) -> Dict:
        return self.mcp.call("sqlite", "list_tables", {})
    
    def describe_table(self, table: str) -> Dict:
        return self.mcp.call("sqlite", "describe_table", {"table": table})
    
    def insert(self, table: str, data: Dict) -> Dict:
        return self.mcp.call("sqlite", "insert", {"table": table, "data": data})


class BraveSearchTools:
    """Brave Search tools using native MCP server."""
    
    TOOLS = [
        ("web_search", "Search the web"),
        ("news_search", "Search news articles"),
    ]
    
    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client
    
    @property
    def available(self) -> bool:
        return self.mcp.is_available("brave-search")
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]
    
    def web_search(self, query: str, count: int = 10) -> Dict:
        return self.mcp.call("brave-search", "web_search", {"query": query, "count": count})
    
    def news_search(self, query: str, count: int = 10) -> Dict:
        return self.mcp.call("brave-search", "news_search", {"query": query, "count": count})




class Context7Tools:
    """Context7 library documentation tools."""
    
    TOOLS = [
        ("resolve_library_id", "Resolve library name to ID"),
        ("get_library_docs", "Get library documentation"),
        ("search_docs", "Search documentation"),
        ("list_popular_libraries", "List popular libraries"),
        ("get_function_docs", "Get function documentation"),
        ("get_examples", "Get code examples"),
    ]

    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client

    @property
    def available(self) -> bool:
        return self.mcp.is_available("context7")
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]

    def resolve_library_id(self, library_name: str, language: str = "python") -> Dict:
        return self.mcp.call("context7", "resolve_library_id", {"library_name": library_name, "language": language})

    def get_library_docs(self, library_id: str, topic: str = None, max_tokens: int = 5000) -> Dict:
        return self.mcp.call("context7", "get_library_docs", {"library_id": library_id, "topic": topic, "max_tokens": max_tokens})

    def search_docs(self, query: str, library_id: str = None, language: str = "python") -> List[Dict]:
        return self.mcp.call("context7", "search_docs", {"query": query, "library_id": library_id, "language": language})

    def list_popular_libraries(self, language: str = "python") -> List[Dict]:
        return self.mcp.call("context7", "list_popular_libraries", {"language": language})

    def get_function_docs(self, library_id: str, function_name: str) -> Dict:
        return self.mcp.call("context7", "get_function_docs", {"library_id": library_id, "function_name": function_name})

    def get_examples(self, library_id: str, topic: str = None) -> List[Dict]:
        return self.mcp.call("context7", "get_examples", {"library_id": library_id, "topic": topic})


class PlaywrightTools:
    """Playwright browser automation tools."""
    
    TOOLS = [
        ("navigate", "Navigate to URL"),
        ("click", "Click element"),
        ("fill", "Fill form field"),
        ("get_text", "Get text content"),
        ("get_html", "Get HTML content"),
        ("screenshot", "Take screenshot"),
        ("evaluate", "Evaluate JavaScript"),
        ("wait_for", "Wait for element/URL"),
        ("close_browser", "Close browser"),
    ]

    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client

    @property
    def available(self) -> bool:
        return self.mcp.is_available("playwright")
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]

    def navigate(self, url: str, wait_until: str = "load") -> Dict:
        return self.mcp.call("playwright", "navigate", {"url": url, "wait_until": wait_until})

    def click(self, selector: str) -> Dict:
        return self.mcp.call("playwright", "click", {"selector": selector})

    def fill(self, selector: str, value: str) -> Dict:
        return self.mcp.call("playwright", "fill", {"selector": selector, "value": value})

    def get_text(self, selector: str = None) -> Dict:
        return self.mcp.call("playwright", "get_text", {"selector": selector})

    def get_html(self, selector: str = None) -> Dict:
        return self.mcp.call("playwright", "get_html", {"selector": selector})

    def screenshot(self, path: str = None, full_page: bool = False) -> Dict:
        return self.mcp.call("playwright", "screenshot", {"path": path, "full_page": full_page})

    def evaluate(self, script: str) -> Dict:
        return self.mcp.call("playwright", "evaluate", {"script": script})

    def wait_for(self, selector: str = None, url: str = None, state: str = "visible") -> Dict:
        return self.mcp.call("playwright", "wait_for", {"selector": selector, "url": url, "state": state})

    def close_browser(self) -> Dict:
        return self.mcp.call("playwright", "close_browser", {})


class N8NTools:
    """n8n workflow automation tools."""
    
    TOOLS = [
        ("health_check", "Check n8n health"),
        ("list_workflows", "List workflows"),
        ("get_workflow", "Get workflow details"),
        ("activate_workflow", "Activate workflow"),
        ("deactivate_workflow", "Deactivate workflow"),
        ("execute_workflow", "Execute workflow"),
        ("list_executions", "List executions"),
        ("get_execution", "Get execution details"),
        ("trigger_webhook", "Trigger webhook"),
    ]

    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client

    @property
    def available(self) -> bool:
        return self.mcp.is_available("n8n")
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]

    def health_check(self) -> Dict:
        return self.mcp.call("n8n", "health_check", {})

    def list_workflows(self, active: bool = None) -> Dict:
        return self.mcp.call("n8n", "list_workflows", {"active": active})

    def get_workflow(self, workflow_id: str) -> Dict:
        return self.mcp.call("n8n", "get_workflow", {"workflow_id": workflow_id})

    def activate_workflow(self, workflow_id: str) -> Dict:
        return self.mcp.call("n8n", "activate_workflow", {"workflow_id": workflow_id})

    def deactivate_workflow(self, workflow_id: str) -> Dict:
        return self.mcp.call("n8n", "deactivate_workflow", {"workflow_id": workflow_id})

    def execute_workflow(self, workflow_id: str, data: Dict = None) -> Dict:
        return self.mcp.call("n8n", "execute_workflow", {"workflow_id": workflow_id, "data": data})

    def list_executions(self, workflow_id: str = None, status: str = None) -> Dict:
        return self.mcp.call("n8n", "list_executions", {"workflow_id": workflow_id, "status": status})

    def get_execution(self, execution_id: str) -> Dict:
        return self.mcp.call("n8n", "get_execution", {"execution_id": execution_id})

    def trigger_webhook(self, webhook_path: str, method: str = "POST", data: Dict = None) -> Dict:
        return self.mcp.call("n8n", "trigger_webhook", {"webhook_path": webhook_path, "method": method, "data": data})




class PodmanTools:
    """Podman/Docker container management tools."""
    
    TOOLS = [
        ("list_containers", "List containers"),
        ("list_images", "List images"),
        ("run_container", "Run new container"),
        ("stop_container", "Stop container"),
        ("start_container", "Start container"),
        ("remove_container", "Remove container"),
        ("container_logs", "Get container logs"),
        ("exec_in_container", "Execute command in container"),
        ("pull_image", "Pull image"),
        ("system_info", "Get system info"),
    ]
    
    def __init__(self, mcp_client: MCPClient):
        self.mcp = mcp_client
    
    @property
    def available(self) -> bool:
        return self.mcp.is_available("podman")
    
    def list_tools(self) -> List[Dict]:
        return [{"name": name, "description": desc} for name, desc in self.TOOLS]
    
    def list_containers(self, all: bool = True) -> Dict:
        return self.mcp.call("podman", "list_containers", {"all": all})
    
    def list_images(self) -> Dict:
        return self.mcp.call("podman", "list_images", {})
    
    def run_container(self, image: str, name: str = None, ports: Dict = None,
                      volumes: Dict = None, env: Dict = None, detach: bool = True) -> Dict:
        return self.mcp.call("podman", "run_container", {
            "image": image, "name": name, "ports": ports,
            "volumes": volumes, "env": env, "detach": detach
        })
    
    def stop_container(self, container: str) -> Dict:
        return self.mcp.call("podman", "stop_container", {"container": container})
    
    def start_container(self, container: str) -> Dict:
        return self.mcp.call("podman", "start_container", {"container": container})
    
    def remove_container(self, container: str, force: bool = False) -> Dict:
        return self.mcp.call("podman", "remove_container", {"container": container, "force": force})
    
    def container_logs(self, container: str, tail: int = 100) -> Dict:
        return self.mcp.call("podman", "container_logs", {"container": container, "tail": tail})
    
    def exec_in_container(self, container: str, command: str) -> Dict:
        return self.mcp.call("podman", "exec_in_container", {"container": container, "command": command})
    
    def pull_image(self, image: str, tag: str = "latest") -> Dict:
        return self.mcp.call("podman", "pull_image", {"image": image, "tag": tag})
    
    def system_info(self) -> Dict:
        return self.mcp.call("podman", "system_info", {})


class MCPToolkit:
    """Combined toolkit with all MCP tools."""
    
    def __init__(self, config_path: str = "mcp.json"):
        self.client = MCPClient(config_path)
        self.github = GitHubTools(self.client)
        self.filesystem = FilesystemTools(self.client)
        self.memory = MemoryTools(self.client)
        self.sqlite = SQLiteTools(self.client)
        self.brave_search = BraveSearchTools(self.client)
        self.context7 = Context7Tools(self.client)
        self.playwright = PlaywrightTools(self.client)
        self.n8n = N8NTools(self.client)
        self.podman = PodmanTools(self.client)
        
        # Alias docker to podman for compatibility
        self.docker = self.podman
    
    def get_available_tools(self) -> List[str]:
        """Get list of available tool categories."""
        tools = []
        if self.github.available:
            tools.append("github")
        if self.filesystem.available:
            tools.append("filesystem")
        if self.memory.available:
            tools.append("memory")
        if self.sqlite.available:
            tools.append("sqlite")
        if self.brave_search.available:
            tools.append("brave-search")
        if self.context7.available:
            tools.append("context7")
        if self.playwright.available:
            tools.append("playwright")
        if self.n8n.available:
            tools.append("n8n")
        if self.podman.available:
            tools.append("podman")
        return tools
    
    def get_status(self) -> Dict:
        """Get status of all MCP tools."""
        return {
            "github": self.github.available,
            "filesystem": self.filesystem.available,
            "memory": self.memory.available,
            "sqlite": self.sqlite.available,
            "brave_search": self.brave_search.available,
            "context7": self.context7.available,
            "playwright": self.playwright.available,
            "n8n": self.n8n.available,
            "podman": self.podman.available,
            "docker": self.podman.available,  # Alias to podman
            "servers_loaded": len(self.client.servers)
        }


def get_mcp_toolkit(config_path: str = "mcp.json") -> MCPToolkit:
    """Get an MCP toolkit instance."""
    return MCPToolkit(config_path)


# =============================================================================
# FXJEFE Local MCP Server Integration (the real asset in this distribution)
# =============================================================================

class FXJEFETools:
    """
    Connector for the FXJEFE Local Security & Productivity Suite MCP server.
    This server provides high-value local tools: security scanning, PDF handling,
    safe browser automation, and safe file operations.
    """

    def __init__(self, server_script: str = None):
        self.server_script = server_script or str(
            Path(__file__).parent.parent / "mcp" / "fxjefe-local-mcp" / "fxjefe_local_mcp_server.py"
        )
        self.available = Path(self.server_script).exists()
        self._process = None  # For future stdio MCP connection

    def get_tools(self) -> List[str]:
        if not self.available:
            return []
        return [
            "static_security_scan",
            "detect_prompt_injection",
            "extract_pdf_text",
            "merge_pdfs",
            "get_pdf_metadata",
            "browser_navigate_and_extract",
            "browser_take_screenshot",
            "safe_list_directory",
            "safe_search_files",
            "safe_read_file",
        ]

    def call(self, tool_name: str, **params) -> Dict:
        """Direct call to FXJEFE tools (current implementation launches the server on demand for one-shot use)."""
        if not self.available:
            return {"error": "FXJEFE Local MCP server not found"}

        # For now we use a simple subprocess bridge for the most useful tools.
        # Full stdio MCP protocol can be added later.
        try:
            if tool_name == "static_security_scan":
                # Run the server in a one-shot mode is complex; for demo we exec a minimal version
                # In real use the agent would launch the server once and keep stdio open.
                return {
                    "status": "info",
                    "message": "FXJEFE security scan tool is available. Launch the server with: python mcp/fxjefe-local-mcp/fxjefe_local_mcp_server.py",
                    "tool": tool_name,
                    "params": params
                }
            # Add more direct bridges for other tools as needed
            return {"error": f"Tool {tool_name} not yet bridged in lightweight mode. Start the FXJEFE MCP server for full access."}
        except Exception as e:
            return {"error": str(e)}

    def status(self) -> Dict:
        return {
            "available": self.available,
            "server_script": self.server_script,
            "tools": self.get_tools(),
            "note": "Run the server with stdio transport for full MCP tool use with Ollama."
        }


# Extend MCPToolkit to include FXJEFE
# (we monkey-patch after class definition for minimal diff)
_original_init = MCPToolkit.__init__

def _new_init(self, config_path: str = "mcp.json"):
    _original_init(self, config_path)
    self.fxjefe = FXJEFETools()
    # Add to status automatically
    if not hasattr(self, '_fxjefe_added'):
        self._fxjefe_added = True

MCPToolkit.__init__ = _new_init

# Patch get_status to include fxjefe
_original_status = MCPToolkit.get_status

def _new_status(self):
    status = _original_status(self)
    if hasattr(self, 'fxjefe'):
        status["fxjefe"] = self.fxjefe.available
        status["fxjefe_tools"] = self.fxjefe.get_tools() if self.fxjefe.available else []
    return status

MCPToolkit.get_status = _new_status


if __name__ == "__main__":
    print("=" * 60)
    print("MCP Client - Native Python Servers (No Docker)")
    print("=" * 60)
    
    toolkit = get_mcp_toolkit()
    status = toolkit.get_status()
    
    print(f"\nðŸ“Š Status:")
    print(f"  GitHub: {'âœ…' if status['github'] else 'âŒ'}")
    print(f"  Filesystem: {'âœ…' if status['filesystem'] else 'âŒ'}")
    print(f"  Memory: {'âœ…' if status['memory'] else 'âŒ'}")
    print(f"  SQLite: {'âœ…' if status['sqlite'] else 'âŒ'}")
    print(f"  Brave Search: {'âœ…' if status['brave_search'] else 'âŒ'}")
    print(f"  Available tools: {toolkit.get_available_tools()}")
    
    if toolkit.github.available:
        print("\nðŸ™ Testing GitHub...")
        user = toolkit.github.get_user()
        print(f"  User: {user.get('login', user)}")
    
    if toolkit.filesystem.available:
        print("\nðŸ“ Testing Filesystem...")
        result = toolkit.filesystem.list_directory(".")
        print(f"  Current dir: {result.get('count', 0)} items")
    
    if toolkit.memory.available:
        print("\nðŸ§  Testing Memory...")
        graph = toolkit.memory.read_graph()
        print(f"  Entities: {graph.get('entity_count', 0)}, Relations: {graph.get('relation_count', 0)}")
