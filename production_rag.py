import os
import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from datetime import datetime
import json
import requests

logger = logging.getLogger(__name__)

# ============================================================================
# DISABLE TELEMETRY AND SET HF TOKEN BEFORE IMPORTS
# ============================================================================
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"
os.environ["POSTHOG_DISABLED"] = "1"
os.environ["DO_NOT_TRACK"] = "1"

# Reduce CUDA fragmentation so the reranker fits on small (8 GB) GPUs even when
# the desktop session is using a chunk of VRAM. Must be set BEFORE torch import.
os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

# HuggingFace token (set your token here or via environment)
HF_TOKEN = os.environ.get("HF_TOKEN", os.environ.get("HUGGINGFACE_TOKEN", ""))
if HF_TOKEN:
    os.environ["HF_TOKEN"] = HF_TOKEN
    os.environ["HUGGINGFACE_TOKEN"] = HF_TOKEN

# ============================================================================
# CONFIGURATION - Edit these settings to customize RAG behavior
# ============================================================================
RAG_CONFIG = {
    # Embedding Configuration
    "embedding_model": "mxbai-embed-large:latest",  # Best quality, 512 ctx
    # Alternative: "nomic-embed-text:latest" for 8K context
    "embedding_host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
    
    # Chunking Configuration (kept conservative because mxbai-embed-large defaults to 512 tokens)
    "chunk_size": 450,
    "chunk_overlap": 120,
    "code_chunk_size": 650,
    
    # Reranker Configuration
    "reranker_model": "BAAI/bge-reranker-v2-m3",
    "reranker_fallback": "cross-encoder/ms-marco-MiniLM-L-12-v2",
    
    # Search Configuration
    "search_k": 20,              # Initial candidates to retrieve
    "rerank_final_k": 5,         # Final results after reranking
    "max_context_tokens": 4000,  # Max tokens for context window
    
    # Database Configuration
    "chroma_path": "./chroma_db",
    "collections": ["knowledge_base", "code_index", "conversation_memory"],
}

# Safe imports with fallbacks
CHROMA_AVAILABLE = False
OLLAMA_EMBED_AVAILABLE = False
OLLAMA_EMBED_COMPAT = False
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
    try:
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
        OLLAMA_EMBED_AVAILABLE = True
    except ImportError:
        logger.warning("ChromaDB OllamaEmbeddingFunction not available")
except ImportError:
    CHROMA_AVAILABLE = False
    logger.warning("ChromaDB not available")


class OllamaEmbeddingFunctionCompat:
    """Compatibility embedding function for ChromaDB when OllamaEmbeddingFunction is missing."""

    def __init__(self, model_name: str, url: str):
        self.model_name = model_name
        self.url = url

    def __call__(self, texts: List[str]) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]

        embeddings: List[List[float]] = []
        for text in texts:
            # HARD SAFETY: mxbai-embed-large and most Ollama embedders have ~512-8192 token limits.
            # Never send more than ~1800 chars in one go to avoid "exceeds context length".
            safe_text = text[:1800] if len(text) > 1800 else text
            try:
                resp = requests.post(
                    self.url,
                    json={"model": self.model_name, "prompt": safe_text},
                    timeout=60,
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"Ollama embeddings error {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                emb = data.get("embedding")
                if emb is None:
                    raise RuntimeError("Ollama embeddings response missing 'embedding'")
                embeddings.append(emb)
            except Exception as e:
                logger.warning(f"Ollama embedding request failed: {e}")
                embeddings.append([])
        return embeddings

RERANKER_AVAILABLE = False
try:
    from sentence_transformers import CrossEncoder
    RERANKER_AVAILABLE = True
except ImportError:
    RERANKER_AVAILABLE = False
    logger.warning("sentence-transformers not available - reranking disabled")


class ProductionRAG:
    """
    Production-ready RAG with:
    - Ollama local embeddings (mxbai-embed-large)
    - BAAI/bge-reranker-v2-m3 reranking
    - Optimized chunking for code and docs
    - Safe error handling
    """

    def __init__(
        self,
        chroma_path: str = None,
        use_reranker: bool = True,
        reranker_model: str = None,
        embedding_model: str = None
    ):
        self.chroma_path = Path(chroma_path or RAG_CONFIG["chroma_path"])
        self.embedding_model = embedding_model or RAG_CONFIG["embedding_model"]
        self.reranker_model = reranker_model or RAG_CONFIG["reranker_model"]
        
        self.chroma_client = None
        self.kb_collection = None
        self.code_collection = None
        self.conv_collection = None
        self.reranker = None
        self.embedding_fn = None

        # Initialize Ollama embedding function
        if OLLAMA_EMBED_AVAILABLE:
            try:
                self.embedding_fn = OllamaEmbeddingFunction(
                    model_name=self.embedding_model,
                    url=RAG_CONFIG["embedding_host"] + "/api/embeddings"
                )
                logger.info(f"✅ Ollama embeddings (native): {self.embedding_model}")
            except Exception as e:
                logger.warning(f"Ollama embeddings unavailable, using ChromaDB default: {e}")
                self.embedding_fn = None
        else:
            # Fallback compatibility embedding function (no chromadb OllamaEmbeddingFunction)
            try:
                self.embedding_fn = OllamaEmbeddingFunctionCompat(
                    model_name=self.embedding_model,
                    url=RAG_CONFIG["embedding_host"] + "/api/embeddings"
                )
                global OLLAMA_EMBED_COMPAT
                OLLAMA_EMBED_COMPAT = True
                logger.info(f"✅ Ollama embeddings (compat): {self.embedding_model}")
            except Exception as e:
                logger.warning(f"Ollama embeddings compat unavailable: {e}")
                self.embedding_fn = None

        # Safe ChromaDB initialization
        global CHROMA_AVAILABLE
        if CHROMA_AVAILABLE:
            try:
                self.chroma_path.mkdir(parents=True, exist_ok=True)

                # ChromaDB 1.x uses PersistentClient
                # Disable telemetry to avoid "capture takes 1 positional argument" error
                persistent_ctor = getattr(chromadb, "PersistentClient", None)
                if persistent_ctor:
                    try:
                        # Try with telemetry disabled via settings
                        self.chroma_client = persistent_ctor(
                            path=str(self.chroma_path),
                            settings=Settings(
                                anonymized_telemetry=False,
                                allow_reset=True,
                            )
                        )
                    except TypeError:
                        # Some versions don't accept all settings
                        self.chroma_client = persistent_ctor(
                            path=str(self.chroma_path)
                        )
                else:
                    # Legacy chromadb 0.3.x
                    legacy_settings = Settings(
                        chroma_db_impl="duckdb+parquet",
                        persist_directory=str(self.chroma_path),
                        anonymized_telemetry=False,
                    )
                    self.chroma_client = chromadb.Client(legacy_settings)
                self._init_collections()
                logger.info(f"✅ ChromaDB initialized at {self.chroma_path}")
            except Exception as e:
                logger.error(f"ChromaDB init failed: {e}")
                CHROMA_AVAILABLE = False

        # Safe reranker initialization with fallback options
        if use_reranker and RERANKER_AVAILABLE:
            try:
                # Try best model first
                self.reranker = CrossEncoder(self.reranker_model, device="cpu")
                logger.info(f"✅ Reranker loaded: {self.reranker_model}")
            except Exception as e:
                logger.warning(f"Primary reranker failed: {e}")
                try:
                    # Fallback to smaller model
                    fallback = RAG_CONFIG["reranker_fallback"]
                    self.reranker = CrossEncoder(fallback, device="cpu")
                    logger.info(f"✅ Reranker loaded (fallback): {fallback}")
                except Exception as e2:
                    logger.warning(f"Reranker completely unavailable: {e2}")
                    self.reranker = None

        # Query cache
        self._cache = {}
        self._cache_max = 100
    
    def get_config(self) -> Dict:
        """Return current RAG configuration for inspection."""
        return {
            "embedding_model": self.embedding_model,
            "reranker_model": self.reranker_model,
            "chroma_path": str(self.chroma_path),
            "chunk_size": RAG_CONFIG["chunk_size"],
            "chunk_overlap": RAG_CONFIG["chunk_overlap"],
            "code_chunk_size": RAG_CONFIG["code_chunk_size"],
            "max_embed_chars": 1800,  # hard safety for Ollama embed models
            "search_k": RAG_CONFIG["search_k"],
            "rerank_final_k": RAG_CONFIG["rerank_final_k"],
            "max_context_tokens": RAG_CONFIG["max_context_tokens"],
            "embedding_available": self.embedding_fn is not None,
            "reranker_available": self.reranker is not None,
            "chroma_available": CHROMA_AVAILABLE,
            "using_ollama_embeddings": self.embedding_fn is not None,
            "ollama_embeddings_mode": (
                "native" if OLLAMA_EMBED_AVAILABLE and self.embedding_fn is not None
                else "compat" if OLLAMA_EMBED_COMPAT and self.embedding_fn is not None
                else "none"
            ),
        }

    def _guard_embedding_dim(self, collection, collection_name: str):
        """
        Refuse to use a collection whose stored embedding dimension does not
        match the current embedder. Prevents Chroma/HNSW segfaults caused by
        inserting mismatched-dim vectors into an existing index.

        On first run (no stamp), probes the embedder and stamps
        ``embed_dim`` + ``embed_model`` into the collection metadata so future
        runs can hard-fail with a readable error instead of crashing natively.
        """
        if self.embedding_fn is None:
            # No custom embedder => Chroma's default is in use; nothing to guard.
            return

        try:
            probe = self.embedding_fn(["dimension probe"])
            if not probe or not probe[0]:
                logger.warning(
                    f"Embedder probe returned empty result; skipping dim guard on '{collection_name}'"
                )
                return
            current_dim = len(probe[0])
        except Exception as e:
            logger.warning(f"Could not probe embedder dimension: {e}")
            return

        meta = dict(collection.metadata or {})
        stored_dim = meta.get("embed_dim")

        if stored_dim is None:
            # First run with the guard — stamp the dimension so future runs can check.
            try:
                meta["embed_dim"] = current_dim
                meta["embed_model"] = self.embedding_model
                collection.modify(metadata=meta)
                logger.info(
                    f"Stamped collection '{collection_name}' with embed_dim={current_dim} "
                    f"(model: {self.embedding_model})"
                )
            except Exception as e:
                logger.warning(f"Could not stamp embed_dim on '{collection_name}': {e}")
            return

        if stored_dim != current_dim:
            raise RuntimeError(
                f"\n❌ Embedding dimension mismatch on collection '{collection_name}'.\n"
                f"   Stored:  {stored_dim}-dim (model: {meta.get('embed_model', '?')})\n"
                f"   Current: {current_dim}-dim (model: {self.embedding_model})\n"
                f"   Inserting into this collection would corrupt the HNSW index "
                f"and crash Chroma.\n"
                f"   Fix: back up and remove the chroma_db folder, then restart to re-index:\n"
                f"     mv chroma_db chroma_db.broken.$(date +%Y%m%d) && python agent_v2.py\n"
            )

    def _init_collections(self):
        """Initialize ChromaDB collections with Ollama embeddings."""
        try:
            # Check if collections already exist - if so, use their existing embedding function
            # to avoid conflicts. Only use Ollama embeddings for NEW collections.
            existing_collections = [c.name for c in self.chroma_client.list_collections()]

            if "knowledge_base" in existing_collections:
                # Use existing collections (with their original embeddings).
                # Use get_or_create_collection so a missing/dropped collection is
                # transparently recreated empty (e.g. after manual repair) instead
                # of raising and disabling RAG entirely.
                self.kb_collection = self.chroma_client.get_or_create_collection(
                    name="knowledge_base", metadata={"hnsw:space": "cosine"}
                )
                self.code_collection = self.chroma_client.get_or_create_collection(
                    name="code_index", metadata={"hnsw:space": "cosine"}
                )
                self.conv_collection = self.chroma_client.get_or_create_collection(
                    name="conversation_memory", metadata={"hnsw:space": "cosine"}
                )
                logger.info("✅ Using existing collections (with original embeddings)")
                logger.info("   To use Ollama embeddings, delete chroma_db folder and re-index")
            else:
                # Create new collections with Ollama embeddings
                if self.embedding_fn:
                    self.kb_collection = self.chroma_client.get_or_create_collection(
                        name="knowledge_base",
                        metadata={"hnsw:space": "cosine"},
                        embedding_function=self.embedding_fn
                    )
                    self.code_collection = self.chroma_client.get_or_create_collection(
                        name="code_index",
                        metadata={"hnsw:space": "cosine"},
                        embedding_function=self.embedding_fn
                    )
                    self.conv_collection = self.chroma_client.get_or_create_collection(
                        name="conversation_memory",
                        metadata={"hnsw:space": "cosine"},
                        embedding_function=self.embedding_fn
                    )
                    logger.info("✅ New collections created with Ollama embeddings")
                else:
                    self.kb_collection = self.chroma_client.get_or_create_collection(
                        name="knowledge_base",
                        metadata={"hnsw:space": "cosine"}
                    )
                    self.code_collection = self.chroma_client.get_or_create_collection(
                        name="code_index",
                        metadata={"hnsw:space": "cosine"}
                    )
                    self.conv_collection = self.chroma_client.get_or_create_collection(
                        name="conversation_memory",
                        metadata={"hnsw:space": "cosine"}
                    )
                    logger.info("✅ New collections created with default embeddings")

            # Dimension guard: refuse to proceed if any collection's stored
            # embedding dimension doesn't match the current embedder. This
            # turns a silent native segfault inside chromadb's Rust core into
            # a clear, actionable Python exception at startup.
            self._guard_embedding_dim(self.kb_collection, "knowledge_base")
            self._guard_embedding_dim(self.code_collection, "code_index")
            self._guard_embedding_dim(self.conv_collection, "conversation_memory")

        except Exception as e:
            logger.error(f"Collection init failed: {e}")
            raise

    def smart_chunk(
        self,
        text: str,
        chunk_size: int = None,
        overlap: int = None,
        filetype: Optional[str] = None
    ) -> List[str]:
        """Smart chunking with configurable parameters.
        
        Args:
            text: Text to chunk
            chunk_size: Override default chunk size (uses RAG_CONFIG if None)
            overlap: Override default overlap (uses RAG_CONFIG if None)
            filetype: File extension to determine chunking strategy
        
        Returns:
            List of text chunks
        """
        if not text or not text.strip():
            return []
        
        # Use config defaults if not specified
        if chunk_size is None:
            chunk_size = RAG_CONFIG["chunk_size"]
        if overlap is None:
            overlap = RAG_CONFIG["chunk_overlap"]

        if filetype in ['.py', '.js', '.java', '.cpp', '.cs', '.rs', '.go', '.ts']:
            return self._chunk_code(text, RAG_CONFIG["code_chunk_size"])
        elif filetype in ['.md', '.txt', '.rst']:
            return self._chunk_markdown(text, chunk_size, overlap)
        elif filetype == '.csv':
            return self._chunk_csv(text, chunk_size)
        else:
            return self._chunk_sliding(text, chunk_size, overlap)

    def _chunk_code(self, code: str, max_size: int) -> List[str]:
        """Properly handles final chunk"""
        chunks = []
        lines = code.split('\n')
        current_chunk = []
        current_size = 0

        for line in lines:
            stripped = line.lstrip()

            # New function/class - check if we should split
            if stripped.startswith(('def ', 'class ', 'async def ', 'function ')):
                if current_size > max_size * 0.7:
                    if current_chunk:
                        chunks.append('\n'.join(current_chunk))
                        current_chunk = []
                        current_size = 0

            current_chunk.append(line)
            current_size += len(line)

            # Hard limit - force split
            if current_size > max_size:
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                    current_chunk = []
                    current_size = 0

        # Add final chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks if chunks else [code]

    def _chunk_markdown(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """Chunk markdown by headers"""
        sections = []
        current_section = []

        for line in text.split('\n'):
            if line.startswith('#'):
                if current_section:
                    sections.append('\n'.join(current_section))
                current_section = [line]
            else:
                current_section.append(line)

        if current_section:
            sections.append('\n'.join(current_section))

        chunks = []
        # Further split large sections
        for section in sections:
            if len(section) < chunk_size:
                chunks.append(section)
            else:
                chunks.extend(self._chunk_sliding(section, chunk_size, overlap))

        return chunks if chunks else [text]

    def _chunk_csv(self, text: str, rows_per_chunk: int = 50) -> List[str]:
        """Chunk CSV preserving header"""
        lines = text.split('\n')
        if not lines:
            return []

        header = lines[0]
        chunks = []

        for i in range(1, len(lines), rows_per_chunk):
            chunk_lines = [header] + lines[i:i + rows_per_chunk]
            chunk_text = '\n'.join(chunk_lines)
            if chunk_text.strip():
                chunks.append(chunk_text)

        return chunks if chunks else [text]

    def _chunk_sliding(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """Sliding window - word-based"""
        words = text.split()
        if not words:
            return []

        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk_words = words[i:i + chunk_size]
            if chunk_words:
                chunks.append(' '.join(chunk_words))

        return chunks if chunks else [text]

    def index_file(self, filepath: str) -> Dict:
        """Safe file indexing with comprehensive error handling"""
        if not CHROMA_AVAILABLE:
            return {"success": False, "error": "ChromaDB not available"}

        path = Path(filepath)
        if not path.exists():
            return {"success": False, "error": f"File not found: {filepath}"}

        try:
            # Read file with encoding fallback
            content = None
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    with open(path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue

            if content is None:
                return {"success": False, "error": "Could not decode file"}

            # Extra safety: truncate absurdly long single files before chunking
            if len(content) > 120_000:
                content = content[:120_000] + "\n... [truncated for embedding safety]"

            # Smart chunking
            chunks = self.smart_chunk(content, filetype=path.suffix)

            if not chunks:
                return {"success": False, "error": "No chunks generated"}

            # Select collection
            collection = self.code_collection if path.suffix in [
                '.py', '.js', '.java', '.cpp', '.cs', '.rs', '.go'
            ] else self.kb_collection

            # Generate IDs
            timestamp = datetime.now().isoformat()
            ids = [f"{path.stem}_{timestamp}_{i}" for i in range(len(chunks))]

            # Metadata
            metadatas = [
                {
                    "source": str(path),
                    "chunk_id": i,
                    "total_chunks": len(chunks),
                    "filetype": path.suffix,
                    "indexed_at": timestamp
                }
                for i in range(len(chunks))
            ]

            # Add to ChromaDB
            collection.add(
                documents=chunks,
                ids=ids,
                metadatas=metadatas
            )

            logger.info(f"✅ Indexed {path.name}: {len(chunks)} chunks")
            return {
                "success": True,
                "chunks": len(chunks),
                "file": str(path)
            }

        except Exception as e:
            logger.error(f"Index error for {filepath}: {e}")
            return {"success": False, "error": str(e)}

    def hybrid_search(
        self,
        query: str,
        k: int = 20,
        rerank: bool = True,
        final_k: int = 5
    ) -> List[Dict]:
        """Handles empty collections and missing reranker"""
        if not CHROMA_AVAILABLE:
            return []

        # Check cache. Include rerank flag so a reranked call doesn't return
        # a cached non-reranked list (or vice versa).
        cache_key = f"{query}_{k}_{final_k}_{int(bool(rerank))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        results = []

        try:
            # Search knowledge base with safety checks
            kb_results = self.kb_collection.query(
                query_texts=[query],
                n_results=k
            )

            kb_docs = kb_results.get('documents', [[]])[0]
            kb_metas = kb_results.get('metadatas', [[]])[0]
            kb_dists = kb_results.get('distances', [[]])[0]

            # Ensure all lists are same length
            min_len = min(len(kb_docs), len(kb_metas), len(kb_dists))

            for i in range(min_len):
                results.append({
                    'content': kb_docs[i],
                    'metadata': kb_metas[i],
                    'score': 1 - kb_dists[i],
                    'source': 'kb'
                })

        except Exception as e:
            logger.warning(f"KB search failed: {e}")

        try:
            # Search code index
            code_results = self.code_collection.query(
                query_texts=[query],
                n_results=k
            )

            code_docs = code_results.get('documents', [[]])[0]
            code_metas = code_results.get('metadatas', [[]])[0]
            code_dists = code_results.get('distances', [[]])[0]

            min_len = min(len(code_docs), len(code_metas), len(code_dists))

            for i in range(min_len):
                results.append({
                    'content': code_docs[i],
                    'metadata': code_metas[i],
                    'score': 1 - code_dists[i],
                    'source': 'code'
                })

        except Exception as e:
            logger.warning(f"Code search failed: {e}")

        if not results:
            return []

        # Rerank if available
        if rerank and self.reranker:
            pairs = [[query, r['content']] for r in results]
            if pairs:
                rerank_scores = None
                try:
                    rerank_scores = self.reranker.predict(pairs)
                except Exception as e:
                    # On CUDA OOM, retry once on CPU. The 8 GB consumer GPUs
                    # in this project share VRAM with the desktop session and
                    # the reranker (~568 MB + activations) doesn't always fit.
                    is_oom = "out of memory" in str(e).lower() or "OutOfMemoryError" in type(e).__name__
                    if is_oom:
                        logger.warning(f"Reranker OOM on GPU, retrying on CPU: {e}")
                        try:
                            import torch
                            torch.cuda.empty_cache()
                            self.reranker.model.to("cpu")
                            try:
                                self.reranker._target_device = torch.device("cpu")
                            except Exception:
                                pass
                            rerank_scores = self.reranker.predict(pairs)
                        except Exception as e2:
                            logger.warning(f"Reranker CPU fallback also failed: {e2}")
                    else:
                        logger.warning(f"Reranking failed: {e}")

                if rerank_scores is not None:
                    for result, score in zip(results, rerank_scores):
                        result['rerank_score'] = float(score)

        # Always sort by best available score so kb and code hits interleave
        # fairly. Without this, when rerank is off or fails, results stay in
        # append order ([kb..., code...]) and code hits get sliced off.
        results.sort(
            key=lambda r: r.get('rerank_score', r.get('score', 0.0)),
            reverse=True,
        )

        # Take top final_k
        final_results = results[:final_k]

        # Cache
        if len(self._cache) >= self._cache_max:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = final_results

        return final_results

    def search(self, query: str, k: int = 5) -> List[str]:
        """Legacy compatibility wrapper - returns list of strings"""
        results = self.hybrid_search(query, k=k*2, final_k=k)
        return [r['content'] for r in results]

    def get_context_for_query(
        self,
        query: str,
        max_tokens: int = 4000
    ) -> str:
        """Get context with better token estimation"""
        results = self.hybrid_search(query, k=20, final_k=10)

        if not results:
            return ""

        context_parts = []
        token_count = 0

        for result in results:
            content = result['content']
            # Better token estimation (approx ~3.5 chars per token)
            tokens = len(content) // 3.5

            if token_count + tokens > max_tokens:
                # Try to include partial content
                remaining_tokens = max_tokens - token_count
                if remaining_tokens > 50: # Minimum useful chunk
                    chars = int(remaining_tokens * 3.5)
                    content = content[:chars] + "..."
                else:
                    break

            source = result['metadata'].get('source', 'Unknown')
            score = result.get('rerank_score', result.get('score', 0))

            context_parts.append(
                f"[{Path(source).name}] (relevance: {score:.2f})\n{content}\n"
            )
            token_count += tokens

        return "\n---\n".join(context_parts)

    def index_directory(
        self,
        directory: str,
        extensions: Optional[List[str]] = None,
        max_files: int = 1000
    ) -> Dict:
        """Safe directory indexing with limits"""
        if extensions is None:
            extensions = [
                '.py', '.js', '.java', '.cpp', '.cs', '.rs', '.go',
                '.md', '.txt', '.rst',
                '.json', '.yaml', '.yml', '.toml',
                '.csv', '.tsv',
                '.sql',
                '.sh', '.bash', '.ps1'
            ]

        dir_path = Path(directory)
        if not dir_path.is_dir():
            return {"success": False, "error": "Not a directory"}

        # === VERY AGGRESSIVE EXCLUDES (this folder only) ===
        EXCLUDE_DIR_PARTS = {
            ".venv", "venv", ".activation_env", "site-packages", "__pycache__",
            ".git", "node_modules", "dist", "build", "egg-info",
            "personal_ai_training", "FXJEFE_Project", "searxng-master",
            "hf-mcp-server-main", "mcp_servers", "mcp", ".conda", "conda-meta"
        }

        def _should_skip(p: Path) -> bool:
            p_str = str(p).lower().replace("\\", "/")
            # Hard blocks for any venv / env / site-packages anywhere in path
            if any(x in p_str for x in (".venv", ".activation_env", "/site-packages/", "/site-packages\\")):
                return True
            # Block by directory part
            for part in p.parts:
                low = part.lower()
                if low in EXCLUDE_DIR_PARTS or any(b in low for b in EXCLUDE_DIR_PARTS):
                    return True
            return False

        results = {
            "success": True,
            "indexed": 0,
            "failed": 0,
            "skipped": 0,
            "files": []
        }

        MAX_FILE_SIZE = 250 * 1024   # 250 KB — anything bigger almost always causes embedding context errors

        file_count = 0
        for file_path in dir_path.rglob('*'):
            if file_count >= max_files:
                results["skipped"] = max_files
                break

            if _should_skip(file_path):
                results["skipped"] += 1
                continue

            if file_path.is_file() and file_path.suffix in extensions:
                try:
                    if file_path.stat().st_size > MAX_FILE_SIZE:
                        results["skipped"] += 1
                        continue
                except Exception:
                    pass

                file_count += 1
                result = self.index_file(str(file_path))

                if result.get("success"):
                    results["indexed"] += 1
                    results["files"].append(str(file_path))
                else:
                    results["failed"] += 1

        return results

    def get_stats(self) -> Dict:
        """Get RAG statistics with real document counts."""
        if not CHROMA_AVAILABLE:
            return {"status": "unavailable"}

        stats = {
            "status": "active",
            "reranker": "enabled" if self.reranker else "disabled",
            "collections": {}
        }

        try:
            kb_count = self.kb_collection.count() if self.kb_collection else 0
            code_count = self.code_collection.count() if self.code_collection else 0
            conv_count = self.conv_collection.count() if self.conv_collection else 0
            # Use the canonical collection names so callers can look up by name
            stats["collections"]["knowledge_base"] = kb_count
            stats["collections"]["code_index"] = code_count
            stats["collections"]["conversation_memory"] = conv_count
            stats["total_documents"] = kb_count + code_count + conv_count
        except Exception as e:
            stats["error"] = str(e)

        return stats

# Singleton
_rag_instance: Optional[ProductionRAG] = None

def get_rag(
    chroma_path: str = "./chroma_db",
    use_reranker: bool = True
) -> ProductionRAG:
    """Get production RAG singleton"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = ProductionRAG(chroma_path, use_reranker)
    return _rag_instance

if __name__ == "__main__":
    print("Testing Production RAG...")
    rag = get_rag()

    # Show stats
    stats = rag.get_stats()
    print(f"\nStats: {json.dumps(stats, indent=2)}")

    # Test chunking
    test_code = """
def function1():
    pass

def function2():
    pass

class MyClass:
    def method(self):
        pass
"""
    chunks = rag.smart_chunk(test_code, filetype='.py')
    print(f"\nChunked into {len(chunks)} parts")

    # Test search (should handle empty gracefully)
    results = rag.hybrid_search("test query")
    print(f"\nSearch returned {len(results)} results")

    print("\n✅ All tests passed!")
