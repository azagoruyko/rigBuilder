import os
import json
import hashlib
import xml.etree.ElementTree as ET
from typing import List, Tuple, Dict, Any

from . import core
from .ai import engine
from .settings import settings
from .utils import loadJson, saveJson

class ModuleIndexer:
    """
    Handles indexing of modules and semantic search using vector embeddings.
    """
    def __init__(self, filePath: str = ""):
        self.filePath: str = filePath
        self.cache: Dict[str, Any] = {"modules": {}, "model": ""}

    def refresh(self):
        """Reload the cache from the current index file."""
        if not self.filePath:
            return
        self.cache = self._loadCache()

    def _loadCache(self) -> Dict[str, Any]:
        """Load the index cache from disk."""
        if not self.filePath or not os.path.exists(self.filePath):
            return {"modules": {}, "model": ""}
            
        try:
            data = loadJson(self.filePath)
            return data
        except Exception as e:
            print(f"Error loading index cache: {e}")
            return {"modules": {}, "model": ""}

    def _saveCache(self):
        """Save the index cache to disk."""
        if not self.filePath:
            return
            
        os.makedirs(os.path.dirname(self.filePath), exist_ok=True)
        try:
            saveJson(self.filePath, self.cache)
        except Exception as e:
            print(f"Error saving index cache: {e}")

    def _getMtime(self, filePath: str) -> float:
        """Get the last modification time of a file."""
        return os.path.getmtime(filePath)

    def _extractIndexableText(self, filePath: str) -> str:
        """Extract name, docs, and attributes labels for indexing using core.Module."""
        try:
            m = core.Module.loadFromFile(filePath)
            name = m.name()
            doc = m.doc()

            # Get the first paragraph or generic description for context
            summary = doc.split("\n\n")[0] if "\n\n" in doc else doc

            # Extract attribute names/labels to help with keyword matching
            attr_text = ", ".join([a.name() for a in m.attributes() if a.name()])
            
            # Construct a rich payload for embedding
            return f"Module: {name}. Summary: {summary}. Keywords: {attr_text}. Full help: {doc}"
        except Exception as e:
            print(f"Error extracting text from {filePath}: {e}")
            return ""

    async def indexModules(self, folder: str, force: bool = False):
        """
        Walks through the modules directory and generates embeddings for new/changed files.
        """
        if not engine.OLLAMA_AVAILABLE:
            print("Ollama not available, skipping semantic indexing.")
            return

        self.refresh() # Ensure we have the latest cache before indexing
        changed = False
        
        # Initial model assignment or model mismatch notification
        currentModel = settings.ollamaEmbeddingModel
        cachedModel = self.cache.get("model")
        
        if not cachedModel:
            self.cache["model"] = currentModel
            changed = True
        elif cachedModel != currentModel:
            print(f"Note: Current embedding model ({currentModel}) differs from the index ({cachedModel}).")
            print("Please delete 'moduleIndex.json' in your workspace to force a full re-index.")

        moduleFiles = core.Module.listModules(folder)

        for f in moduleFiles:
            absPath = os.path.abspath(f).lower()
            currentMtime = self._getMtime(absPath)
            
            cachedData = self.cache["modules"].get(absPath)
            
            # Index if forced, or mtime changed, or never indexed
            if force or not cachedData or cachedData.get("mtime") != currentMtime:
                print(f"Indexing: {os.path.basename(f)}...")
                text = self._extractIndexableText(absPath)
                if not text:
                    continue
                    
                embedding = await engine.embed(text)
                if embedding:
                    self.cache["modules"][absPath] = {
                        "mtime": currentMtime,
                        "embedding": embedding,
                        "name": os.path.splitext(os.path.basename(f))[0]
                    }
                    changed = True
        
        if changed:
            self._saveCache()
            print("Semantic index updated.")

    async def search(self, query: str, k: int = 5) -> List[Tuple[str, float]]:
        """
        Search modules by natural language query.
        Returns a list of (module_path, similarity_score) tuples.
        """
        queryEmbedding = await engine.embed(query.lower())
        if not queryEmbedding:
            return []

        results = []
        for path, data in self.cache["modules"].items():
            embedding = data.get("embedding")
            if embedding is None:
                continue
            
            score = engine.cosineSimilarity(queryEmbedding, embedding)
            results.append((path, score))

        # Sort by score descending and return top_k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]
