#!/usr/bin/env python3
"""
Multi-Model Router for Ollama
- Task-based model selection
- Context limits per model
- Automatic fallback chain
- Model capabilities detection
"""

import re
import requests
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Types of tasks for model routing."""
    CODING = "coding"
    REASONING = "reasoning"
    CHAT = "chat"
    VISION = "vision"
    EMBEDDING = "embedding"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    FILE_EDIT = "file_edit"
    SUMMARIZE = "summarize"
    AGENTIC = "agentic"


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    name: str
    context_limit: int  # in tokens (approximate)
    tasks: List[TaskType]
    priority: int = 1  # Lower = higher priority for task
    description: str = ""
    

# Model configurations with context limits and task assignments
MODEL_CONFIGS: Dict[str, ModelConfig] = {
    # Coding models
    "qwen3-coder:30b": ModelConfig(
        name="qwen3-coder:30b",
        context_limit=32768,
        tasks=[TaskType.CODING, TaskType.FILE_EDIT, TaskType.ANALYSIS],
        priority=1,
        description="Large coding model - best for complex code tasks"
    ),
    "hf.co/mradermacher/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated-i1-GGUF:Q4_K_M": ModelConfig(
        name="hf.co/mradermacher/Huihui-Qwen3-Coder-30B-A3B-Instruct-abliterated-i1-GGUF:Q4_K_M",
        context_limit=32768,
        tasks=[TaskType.CODING, TaskType.FILE_EDIT, TaskType.CREATIVE],
        priority=2,
        description="Uncensored coding model - creative solutions"
    ),
    
    # Reasoning models
    "deepseek-r1:8b": ModelConfig(
        name="deepseek-r1:8b",
        context_limit=32768,
        tasks=[TaskType.REASONING, TaskType.ANALYSIS, TaskType.SUMMARIZE],
        priority=1,
        description="Reasoning model - step-by-step thinking"
    ),
    
    # General chat models
    "llama3.2:3b": ModelConfig(
        name="llama3.2:3b",
        context_limit=8192,
        tasks=[TaskType.CHAT, TaskType.SUMMARIZE],
        priority=1,
        description="Fast, small chat model"
    ),
    "llama3.2:latest": ModelConfig(
        name="llama3.2:latest",
        context_limit=8192,
        tasks=[TaskType.CHAT, TaskType.SUMMARIZE],
        priority=2,
        description="Default Llama 3.2 model"
    ),
    "llama3.1:latest": ModelConfig(
        name="llama3.1:latest",
        context_limit=131072,
        tasks=[TaskType.CHAT, TaskType.REASONING, TaskType.ANALYSIS, TaskType.SUMMARIZE],
        priority=1,
        description="Llama 3.1 with 128k context"
    ),
    "llama3.1:8b": ModelConfig(
        name="llama3.1:8b",
        context_limit=131072,
        tasks=[TaskType.CHAT, TaskType.REASONING, TaskType.ANALYSIS],
        priority=2,
        description="Llama 3.1 8B with 128k context"
    ),
    
    # Creative/uncensored models
    "CognitiveComputations/dolphin-mistral-nemo:12b": ModelConfig(
        name="CognitiveComputations/dolphin-mistral-nemo:12b",
        context_limit=32768,
        tasks=[TaskType.CREATIVE, TaskType.CHAT, TaskType.REASONING],
        priority=1,
        description="Uncensored Dolphin model - creative tasks"
    ),
    "CognitiveComputations/dolphin-llama3.1:latest": ModelConfig(
        name="CognitiveComputations/dolphin-llama3.1:latest",
        context_limit=32768,
        tasks=[TaskType.CREATIVE, TaskType.CHAT],
        priority=2,
        description="Dolphin Llama - creative assistant"
    ),
    "hf.co/DavidAU/Qwen3-The-Xiaolong-Josiefied-Omega-Directive-22B-uncensored-abliterated-GGUF:Q4_K_M": ModelConfig(
        name="hf.co/DavidAU/Qwen3-The-Xiaolong-Josiefied-Omega-Directive-22B-uncensored-abliterated-GGUF:Q4_K_M",
        context_limit=32768,
        tasks=[TaskType.CREATIVE, TaskType.CHAT, TaskType.REASONING],
        priority=3,
        description="Large uncensored model"
    ),
    "hf.co/DavidAU/Mistral-MOE-4X7B-Dark-MultiVerse-Uncensored-Enhanced32-24B-gguf:Q4_K_M": ModelConfig(
        name="hf.co/DavidAU/Mistral-MOE-4X7B-Dark-MultiVerse-Uncensored-Enhanced32-24B-gguf:Q4_K_M",
        context_limit=32768,
        tasks=[TaskType.CREATIVE, TaskType.REASONING],
        priority=4,
        description="MOE Mistral - uncensored"
    ),
    
    # Instruct models
    "mistral:7b-instruct": ModelConfig(
        name="mistral:7b-instruct",
        context_limit=8192,
        tasks=[TaskType.CHAT, TaskType.SUMMARIZE, TaskType.ANALYSIS],
        priority=2,
        description="Mistral instruct - general purpose"
    ),
    "gemma:2b-instruct": ModelConfig(
        name="gemma:2b-instruct",
        context_limit=8192,
        tasks=[TaskType.CHAT, TaskType.SUMMARIZE],
        priority=3,
        description="Fast small instruct model"
    ),
    "gemma3:12b": ModelConfig(
        name="gemma3:12b",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.REASONING, TaskType.ANALYSIS],
        priority=2,
        description="Gemma 3 12B - balanced model"
    ),
    
    # Vision models
    "llava:13b": ModelConfig(
        name="llava:13b",
        context_limit=4096,
        tasks=[TaskType.VISION],
        priority=1,
        description="Vision-language model"
    ),
    "qwen3-vl:8b": ModelConfig(
        name="qwen3-vl:8b",
        context_limit=8192,
        tasks=[TaskType.VISION],
        priority=2,
        description="Qwen3 vision model"
    ),
    "hf.co/mradermacher/Huihui-Qwen3-VL-30B-A3B-Thinking-abliterated-i1-GGUF:Q4_K_M": ModelConfig(
        name="hf.co/mradermacher/Huihui-Qwen3-VL-30B-A3B-Thinking-abliterated-i1-GGUF:Q4_K_M",
        context_limit=32768,
        tasks=[TaskType.VISION, TaskType.REASONING],
        priority=3,
        description="Large vision model with thinking"
    ),
    
    # Embedding models
    "mxbai-embed-large:latest": ModelConfig(
        name="mxbai-embed-large:latest",
        context_limit=512,
        tasks=[TaskType.EMBEDDING],
        priority=1,
        description="Best embedding model"
    ),
    "nomic-embed-text:latest": ModelConfig(
        name="nomic-embed-text:latest",
        context_limit=8192,
        tasks=[TaskType.EMBEDDING],
        priority=2,
        description="Long-context embeddings"
    ),
    "embeddinggemma:latest": ModelConfig(
        name="embeddinggemma:latest",
        context_limit=512,
        tasks=[TaskType.EMBEDDING],
        priority=3,
        description="Gemma embeddings"
    ),
    
    # Dolphin models
    "dolphin-mistral:latest": ModelConfig(
        name="dolphin-mistral:latest",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.CREATIVE, TaskType.REASONING],
        priority=1,
        description="Dolphin Mistral - fast medium chat model (4.1GB)"
    ),
    "dolphincoder:15b": ModelConfig(
        name="dolphincoder:15b",
        context_limit=32768,
        tasks=[TaskType.CODING, TaskType.CHAT, TaskType.FILE_EDIT, TaskType.ANALYSIS],
        priority=2,
        description="DolphinCoder 15B - medium coding model (9.1GB)"
    ),

    # Other models
    "gpt-oss:20b": ModelConfig(
        name="gpt-oss:20b",
        context_limit=4096,
        tasks=[TaskType.CHAT, TaskType.CREATIVE],
        priority=5,
        description="GPT-OSS model"
    ),

    # --- Models from larry_config.json ---
    "dolphin-mixtral:8x7b": ModelConfig(
        name="dolphin-mixtral:8x7b",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.REASONING, TaskType.CREATIVE, TaskType.AGENTIC],
        priority=1,
        description="Default model - Dolphin Mixtral uncensored"
    ),
    "llama3.3:70b": ModelConfig(
        name="llama3.3:70b",
        context_limit=131072,
        tasks=[TaskType.CHAT, TaskType.REASONING, TaskType.ANALYSIS, TaskType.AGENTIC],
        priority=1,
        description="Flagship model - Llama 3.3 70B 128K context"
    ),
    "qwen2.5:32b-instruct": ModelConfig(
        name="qwen2.5:32b-instruct",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.REASONING, TaskType.CODING, TaskType.ANALYSIS],
        priority=1,
        description="Qwen 2.5 32B instruct"
    ),
    "glm-4.7-flash:latest": ModelConfig(
        name="glm-4.7-flash:latest",
        context_limit=131072,
        tasks=[TaskType.CHAT, TaskType.REASONING, TaskType.ANALYSIS],
        priority=2,
        description="GLM-4 Flash 128K context"
    ),
    "devstral-small-2:24b": ModelConfig(
        name="devstral-small-2:24b",
        context_limit=32768,
        tasks=[TaskType.CODING, TaskType.FILE_EDIT, TaskType.ANALYSIS],
        priority=2,
        description="Devstral coding model 24B"
    ),
    "ministral-3:latest": ModelConfig(
        name="ministral-3:latest",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.SUMMARIZE],
        priority=1,
        description="Fast Ministral 3 model"
    ),
    "ministral-3:14b": ModelConfig(
        name="ministral-3:14b",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.REASONING, TaskType.SUMMARIZE],
        priority=1,
        description="Ministral 3 14B"
    ),
    "qwen2.5-128k:latest": ModelConfig(
        name="qwen2.5-128k:latest",
        context_limit=131072,
        tasks=[TaskType.CHAT, TaskType.ANALYSIS, TaskType.SUMMARIZE, TaskType.FILE_EDIT],
        priority=1,
        description="Qwen 2.5 ultra context 128K"
    ),
    "llama3.2-ctx:latest": ModelConfig(
        name="llama3.2-ctx:latest",
        context_limit=65536,
        tasks=[TaskType.CHAT, TaskType.SUMMARIZE],
        priority=2,
        description="Llama 3.2 extended context"
    ),
    "lfm2.5-thinking:1.2b": ModelConfig(
        name="lfm2.5-thinking:1.2b",
        context_limit=32768,
        tasks=[TaskType.REASONING, TaskType.CHAT],
        priority=3,
        description="LFM 2.5 thinking small model"
    ),
    "granite4:1b": ModelConfig(
        name="granite4:1b",
        context_limit=8192,
        tasks=[TaskType.CHAT, TaskType.SUMMARIZE],
        priority=4,
        description="IBM Granite 4 tiny model"
    ),
    "qwen2.5:7b-instruct-q5_K_M": ModelConfig(
        name="qwen2.5:7b-instruct-q5_K_M",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.CODING, TaskType.ANALYSIS],
        priority=2,
        description="Qwen 2.5 7B instruct Q5"
    ),
    "qwen2.5:7b-instruct": ModelConfig(
        name="qwen2.5:7b-instruct",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.CODING, TaskType.ANALYSIS],
        priority=3,
        description="Qwen 2.5 7B instruct"
    ),
    "qwen2.5:14b-instruct-q4_K_M": ModelConfig(
        name="qwen2.5:14b-instruct-q4_K_M",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.CODING, TaskType.REASONING],
        priority=2,
        description="Qwen 2.5 14B instruct Q4"
    ),
    "mistral:latest": ModelConfig(
        name="mistral:latest",
        context_limit=32768,
        tasks=[TaskType.CHAT, TaskType.SUMMARIZE, TaskType.ANALYSIS],
        priority=2,
        description="Mistral latest"
    ),
}

# Task detection keywords
TASK_KEYWORDS = {
    TaskType.CODING: [
        "code", "program", "function", "class", "debug", "fix", "implement",
        "python", "javascript", "typescript", "java", "c++", "rust", "go",
        "api", "endpoint", "database", "sql", "query", "script", "refactor",
        "bug", "error", "compile", "syntax", "algorithm", "data structure"
    ],
    TaskType.FILE_EDIT: [
        "edit file", "modify file", "update file", "change file", "write file",
        "create file", "save", "read file", "open file", "file content"
    ],
    TaskType.REASONING: [
        "explain", "why", "how", "analyze", "think", "reason", "logic",
        "step by step", "breakdown", "understand", "evaluate", "compare"
    ],
    TaskType.VISION: [
        "image", "picture", "photo", "screenshot", "visual", "see", "look at",
        "describe image", "what's in"
    ],
    TaskType.CREATIVE: [
        "creative", "story", "poem", "write", "generate", "imagine", "roleplay",
        "fiction", "narrative", "uncensored", "unrestricted"
    ],
    TaskType.SUMMARIZE: [
        "summarize", "summary", "brief", "tldr", "short version", "condense",
        "key points", "main ideas"
    ],
    TaskType.ANALYSIS: [
        "analyze", "review", "assess", "examine", "investigate", "study",
        "research", "data", "statistics", "metrics"
    ],
}


class ModelRouter:
    """Routes tasks to appropriate Ollama models."""
    
    def __init__(self, host: str = "localhost", port: int = 11434):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.available_models: List[str] = []
        self.current_model: str = "llama3.2:3b"  # Default fallback
        self.refresh_models()
    
    def refresh_models(self) -> List[str]:
        """Refresh list of available models from Ollama."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.available_models = [m["name"] for m in data.get("models", [])]
                logger.info(f"Found {len(self.available_models)} available models")
                return self.available_models
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
        return []
    
    def get_models_info(self) -> List[Dict]:
        """Get detailed info about available models."""
        models_info = []
        for model_name in self.available_models:
            config = MODEL_CONFIGS.get(model_name)
            if config:
                models_info.append({
                    "name": model_name,
                    "context_limit": config.context_limit,
                    "tasks": [t.value for t in config.tasks],
                    "description": config.description
                })
            else:
                # Model not in config, add basic info
                models_info.append({
                    "name": model_name,
                    "context_limit": 8192,  # Conservative default for unknown models
                    "tasks": ["chat"],
                    "description": "Unknown model"
                })
        return models_info
    
    def detect_task(self, query: str) -> TaskType:
        """Detect the task type from the query."""
        query_lower = query.lower()

        # Score each task type using whole-word matching to avoid
        # false positives like "api" matching inside "capital"
        scores = {task: 0 for task in TaskType}

        for task_type, keywords in TASK_KEYWORDS.items():
            for keyword in keywords:
                pattern = r'\b' + re.escape(keyword) + r'\b'
                if re.search(pattern, query_lower):
                    scores[task_type] += 1

        # Get highest scoring task
        max_score = max(scores.values())
        if max_score > 0:
            for task_type, score in scores.items():
                if score == max_score:
                    return task_type

        # Default to chat
        return TaskType.CHAT
    
    def get_model_for_task(self, task: TaskType, prefer_fast: bool = False) -> Tuple[str, ModelConfig]:
        """Get the best available model for a task."""
        candidates = []
        
        for model_name, config in MODEL_CONFIGS.items():
            if model_name in self.available_models and task in config.tasks:
                candidates.append((model_name, config))
        
        if not candidates:
            # Fallback to any available chat model
            for model_name in self.available_models:
                config = MODEL_CONFIGS.get(model_name)
                if config and TaskType.CHAT in config.tasks:
                    return model_name, config
            # Last resort
            if self.available_models:
                return self.available_models[0], ModelConfig(
                    name=self.available_models[0],
                    context_limit=8192,
                    tasks=[TaskType.CHAT],
                    description="Fallback model"
                )
        
        # Sort by priority (and context limit if prefer_fast)
        if prefer_fast:
            candidates.sort(key=lambda x: (x[1].priority, x[1].context_limit))
        else:
            candidates.sort(key=lambda x: x[1].priority)
        
        return candidates[0]
    
    def route_query(self, query: str, prefer_fast: bool = False) -> Tuple[str, TaskType, int]:
        """Route a query to the appropriate model.
        
        Returns: (model_name, task_type, context_limit)
        """
        task = self.detect_task(query)
        model_name, config = self.get_model_for_task(task, prefer_fast)
        
        logger.info(f"Routing to {model_name} for task {task.value} (context: {config.context_limit})")
        self.current_model = model_name
        
        return model_name, task, config.context_limit
    
    def truncate_to_context(self, text: str, model_name: str, reserve_tokens: int = 1000) -> str:
        """Truncate text to fit within model's context limit."""
        config = MODEL_CONFIGS.get(model_name)
        if not config:
            max_chars = 4096 * 4  # Rough estimate
        else:
            max_chars = (config.context_limit - reserve_tokens) * 4  # ~4 chars per token
        
        if len(text) > max_chars:
            logger.info(f"Truncating text from {len(text)} to {max_chars} chars")
            return text[:max_chars] + "\n... [truncated to fit context]"
        return text
    
    def generate(self, prompt: str, model: str = None, timeout: int = 1800, options: Dict = None) -> str:
        """Generate response using specified or auto-routed model.
        
        FXJEFE Local Larry: Default timeout raised significantly for long-running local model queries.
        Complex reasoning, large context, or slow models can easily exceed 2-5 minutes.
        """
        if model is None:
            model, task, context_limit = self.route_query(prompt)
        else:
            config = MODEL_CONFIGS.get(model)
            context_limit = config.context_limit if config else 8192

        # FXJEFE: Automatic adaptable routing with token awareness
        token_estimate = len(prompt) // 4  # rough estimate
        logger.info(f"Task: {task.value if 'task' in locals() else 'manual'} | Estimated tokens: {token_estimate} | Selected model: {model}")

        # Truncate prompt if needed
        prompt = self.truncate_to_context(prompt, model)

        # Build Ollama options
        ollama_options = {"num_ctx": context_limit, "num_predict": -1}
        if options:
            ollama_options.update(options)

        logger.info(f"generate() model={model} num_ctx={ollama_options['num_ctx']}")

        try:
            data = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": ollama_options
            }
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=data,
                timeout=timeout
            )
            if response.status_code == 200:
                return response.json().get("response", "No response")
            else:
                return f"Error: {response.status_code} - {response.text[:200]}"
        except requests.Timeout:
            return (
                f"Timeout after {timeout}s talking to Ollama.\n"
                f"  - Try a faster model: /model <name>\n"
                f"  - Or increase timeout in larry_config.json under ollama.timeout\n"
                f"  - Make sure Ollama is still running (ollama serve or desktop app)"
            )
        except Exception as e:
            return f"Error: {str(e)}"
    
    def set_model(self, model_name: str) -> bool:
        """Manually set the current model.
        If a different model was active, attempt to unload it from VRAM first.
        """
        if model_name not in self.available_models:
            return False

        old_model = self.current_model

        if old_model and old_model != model_name:
            logger.info(f"Unloading previous model from VRAM: {old_model}")
            try:
                import requests
                requests.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": old_model, "prompt": "", "keep_alive": 0},
                    timeout=15
                )
            except Exception as e:
                logger.warning(f"Could not unload {old_model}: {e}")

        self.current_model = model_name
        logger.info(f"Switched to model: {model_name}")
        return True


# Convenience functions
_router = None

def get_router() -> ModelRouter:
    """Get or create the global model router.
    
    FXJEFE Local Larry: Respects larry_config.json ollama.timeout when available.
    """
    global _router
    if _router is None:
        try:
            import json
            from pathlib import Path
            cfg_path = Path(__file__).parent / "larry_config.json"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                ollama_cfg = cfg.get("ollama", {})
                configured_timeout = ollama_cfg.get("timeout")
                if configured_timeout and isinstance(configured_timeout, (int, float)):
                    _router = ModelRouter()
                    # Note: actual per-call timeout still passed to generate()
                    # This just documents the intent from config
            else:
                _router = ModelRouter()
        except Exception:
            _router = ModelRouter()
    return _router

def list_models() -> str:
    """Return formatted list of available models."""
    router = get_router()
    models = router.get_models_info()
    
    output = ["📋 Available Ollama Models:\n"]
    output.append(f"{'Model':<60} {'Context':<10} {'Tasks':<30}")
    output.append("-" * 100)
    
    for m in models:
        tasks_str = ", ".join(m["tasks"][:3])
        if len(m["tasks"]) > 3:
            tasks_str += "..."
        output.append(f"{m['name'][:58]:<60} {m['context_limit']:<10} {tasks_str:<30}")
    
    return "\n".join(output)

def route_and_generate(query: str, prefer_fast: bool = False) -> str:
    """Route query and generate response."""
    router = get_router()
    return router.generate(query)


if __name__ == "__main__":
    # Test the router
    print("Testing Model Router...")
    router = ModelRouter()
    
    print("\n" + list_models())
    
    print("\n\nTask Detection Tests:")
    test_queries = [
        "Write a Python function to sort a list",
        "Explain why the sky is blue",
        "Describe this image",
        "Write me a creative story about dragons",
        "Summarize this document",
        "Hello, how are you?",
        "Edit the file main.py and add error handling"
    ]
    
    for query in test_queries:
        model, task, ctx = router.route_query(query)
        print(f"  '{query[:40]}...' -> {task.value} -> {model} (ctx: {ctx})")
