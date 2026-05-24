#!/usr/bin/env python3
"""
FXJEFE Local Larry - Embedding + Vector Store Setup (i2.3)

Production-grade LangChain + Ollama + Chroma integration.
This replaces ad-hoc embedding code and provides a single source of truth
for vector storage used by RAG, memory handoff, and knowledge features.

Location: GITHUB root (easy testing + importable from src/)
"""

from pathlib import Path
import json
from typing import Optional

# LangChain imports (install via requirements or the ones user showed)
try:
    from langchain_ollama import OllamaEmbeddings
    from langchain_chroma import Chroma
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    print("⚠️  LangChain packages not installed. Run:")
    print("   pip install langchain langchain-ollama langchain-chroma")


class FXJEFEEmbeddings:
    """
    Centralized embedding + vector store manager for FXJEFE Local Larry.
    
    Uses the project's larry_config.json for consistency with:
    - embedding_model
    - chroma_path
    - RAG settings
    """

    def __init__(self, config_path: str = "config/larry_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        
        self.embedding_model_name = self.config.get("rag", {}).get(
            "embedding_model", "nomic-embed-text:latest"
        )
        self.persist_directory = self.config.get("rag", {}).get(
            "chroma_path", "./chroma_db"
        )
        
        self.embeddings = None
        self.vectorstore = None
        
        if LANGCHAIN_AVAILABLE:
            self._init_embeddings()
            self._init_vectorstore()

    def _load_config(self) -> dict:
        """Load configuration with graceful fallback."""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _init_embeddings(self):
        """Initialize Ollama embeddings."""
        try:
            self.embeddings = OllamaEmbeddings(model=self.embedding_model_name)
            print(f"✅ Ollama Embeddings ready: {self.embedding_model_name}")
        except Exception as e:
            print(f"❌ Failed to initialize embeddings: {e}")
            self.embeddings = None

    def _init_vectorstore(self):
        """Initialize Chroma vector store."""
        if not self.embeddings:
            return
            
        try:
            Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
            
            self.vectorstore = Chroma(
                collection_name="fxjefe_local_docs",
                embedding_function=self.embeddings,
                persist_directory=self.persist_directory
            )
            print(f"✅ Chroma Vector Store ready at: {self.persist_directory}")
        except Exception as e:
            print(f"❌ Failed to initialize Chroma: {e}")
            self.vectorstore = None

    def add_texts(self, texts: list[str], metadatas: Optional[list[dict]] = None):
        """Add documents to the vector store."""
        if not self.vectorstore:
            raise RuntimeError("Vector store not initialized")
        return self.vectorstore.add_texts(texts, metadatas=metadatas)

    def similarity_search(self, query: str, k: int = 5):
        """Search for similar documents."""
        if not self.vectorstore:
            raise RuntimeError("Vector store not initialized")
        return self.vectorstore.similarity_search(query, k=k)

    def get_retriever(self, search_kwargs: Optional[dict] = None):
        """Return a retriever for use in LangChain chains."""
        if not self.vectorstore:
            raise RuntimeError("Vector store not initialized")
        return self.vectorstore.as_retriever(
            search_kwargs=search_kwargs or {"k": 5}
        )

    def status(self) -> dict:
        """Return current status for health checks."""
        return {
            "langchain_available": LANGCHAIN_AVAILABLE,
            "embedding_model": self.embedding_model_name,
            "persist_directory": str(self.persist_directory),
            "vectorstore_ready": self.vectorstore is not None,
            "embeddings_ready": self.embeddings is not None,
        }


# Convenience singleton for simple usage
_embeddings_instance: Optional[FXJEFEEmbeddings] = None

def get_embeddings() -> FXJEFEEmbeddings:
    """Get or create the global embeddings instance."""
    global _embeddings_instance
    if _embeddings_instance is None:
        _embeddings_instance = FXJEFEEmbeddings()
    return _embeddings_instance


if __name__ == "__main__":
    print("=" * 60)
    print("FXJEFE Local Larry - Embedding + Vector Store Setup")
    print("=" * 60)
    
    emb = FXJEFEEmbeddings()
    
    print("\nStatus:")
    for k, v in emb.status().items():
        print(f"  {k}: {v}")
    
    if emb.vectorstore:
        print("\n✅ Embedding system fully ready for RAG & Memory Handoff!")
        print("   You can now use get_embeddings() in other modules.")
    else:
        print("\n⚠️  Embedding system partially initialized. Check errors above.")