import os
import json
import xml.etree.ElementTree as ET
from typing import List, Tuple, Dict, Any

from . import core
from ..ai import engine
from .settings import settings
from .utils import loadJson, saveJson, fileHash

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
            return loadJson(self.filePath)
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


    async def indexModules(self, folder: str):
        """
        Walks through the modules directory and generates embeddings for new/changed files.
        """
        self.refresh() # Ensure we have the latest cache before indexing
        changed = False
        force = False
        
        # Initial model assignment
        currentModel = settings.ollamaEmbeddingModel
        cachedModel = self.cache.get("model")
        
        if not cachedModel:
            self.cache["model"] = currentModel
            changed = True
            
        if cachedModel and cachedModel != currentModel:
            if not engine.IS_OLLAMA_AVAILABLE:
                print(f"Note: Current embedding model ({currentModel}) differs from the index ({cachedModel}).")
                print("Re-indexing is pending until Ollama is available.")
            else:
                print(f"Embedding model mismatch ({cachedModel} -> {currentModel}). Forcing full re-index...")
                self.cache["model"] = currentModel
                self.cache["modules"] = {} # Clear old embeddings
                changed = True
                force = True # Force re-indexing of all files

        if not engine.IS_OLLAMA_AVAILABLE:
            if changed:
                self._saveCache() # Save if we just initialized the model name
            return

        moduleFiles = core.Module.listModules(folder)

        for f in moduleFiles:
            currentHash = fileHash(f)

            try:
                relpath = os.path.relpath(f, settings.workspacePath)
            except ValueError:
                relpath = f
            
            cachedData = self.cache["modules"].get(relpath)
            
            # Index if forced, or hash changed, or never indexed
            if force or not cachedData or cachedData.get("hash") != currentHash:
                text = self._extractIndexableText(f)
                if not text:
                    continue

                print(f"Indexing: {os.path.basename(f)}...")
                embedding = await engine.embed(text)

                if embedding:
                    self.cache["modules"][relpath] = {
                        "hash": currentHash,
                        "embedding": embedding,
                        "name": os.path.splitext(os.path.basename(f))[0]
                    }
                    changed = True

        # remove older files from cache
        for relpath in list(self.cache["modules"].keys()):
            f = os.path.join(settings.workspacePath, relpath)
            if not os.path.exists(f):
                del self.cache["modules"][relpath]
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
