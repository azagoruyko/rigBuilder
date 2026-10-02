from __future__ import annotations

import os
import re
from typing import Any

from . import core
from .uidManager import UidManager
from ..ai import engine
from .settings import settings
from .utils import loadJson, saveJson, fileHash, relativePath

class ModuleIndexer:
    """
    Handles indexing of modules and semantic search using vector embeddings.
    """
    def __init__(self, filePath: str = ""):
        self.filePath = filePath
        self.cache = {"modules": {}, "model": ""}

    def refresh(self):
        """Reload the cache from the current index file."""
        if not self.filePath:
            return
        self.cache = self._loadCache()

    def _loadCache(self) -> dict[str, Any]:
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
        """Extract module name, category, and first documentation section for vector indexing."""
        m = core.Module.loadFromFile(filePath)
        doc = (m.doc() or "").strip()

        category = "Root"
        for rootPath in [settings.modulesPath, *settings.moduleDependenciesPaths]:
            relPath = relativePath(filePath, rootPath)
            if relPath == filePath:
                continue

            relDir = os.path.dirname(relPath).replace("\\", "/")
            if rootPath != settings.modulesPath:
                category = os.path.basename(os.path.normpath(rootPath))
            if relDir and relDir != ".":
                category = f"{category}/{relDir}" if category != "Root" else relDir
            break

        # Extract first section (preamble or text under first header)
        sections = re.split(r'\n(?=#{1,6}\s+)', doc)
        firstSection = re.sub(r'^#{1,6}\s+.*\n?', '', sections[0]) if sections else ""

        # Clean code blocks, formatting symbols, and extra whitespace
        firstSection = re.sub(r'```[\s\S]*?```', '', firstSection)
        cleanSummary = re.sub(r'\s+', ' ', re.sub(r'[*_`#]', '', firstSection)).strip()

        return f"Module: {m.name()}. Category: {category}. Summary: {cleanSummary}"

    async def indexModules(self):
        """Index the active workspace's owned and dependency modules by UID."""
        self.refresh() # Ensure we have the latest cache before indexing
        changed = False
        ollamaAvailable = engine.isOllamaAvailable()
        
        # Initial model assignment
        currentModel = settings.ollamaEmbeddingModel
        cachedModel = self.cache.get("model")
        
        if not cachedModel:
            self.cache["model"] = currentModel
            changed = True
            
        if cachedModel and cachedModel != currentModel:
            if not ollamaAvailable:
                print(f"Note: Current embedding model ({currentModel}) differs from the index ({cachedModel}).")
                print("Re-indexing is pending until Ollama is available.")
            else:
                print(f"Embedding model mismatch ({cachedModel} -> {currentModel}). Forcing full re-index...")
                self.cache["model"] = currentModel
                self.cache["modules"] = {} # Clear old embeddings
                changed = True

        moduleFiles = dict(UidManager.uids())
        for uid in list(self.cache["modules"]):
            if uid not in moduleFiles:
                del self.cache["modules"][uid]
                changed = True

        if not ollamaAvailable:
            if changed:
                self._saveCache()
            return

        for uid, f in moduleFiles.items():
            currentHash = fileHash(f)
            cachedData = self.cache["modules"].get(uid)
            
            # Index new modules and modules whose file or source path changed.
            if not cachedData or cachedData.get("hash") != currentHash or cachedData.get("path") != f:
                text = self._extractIndexableText(f)
                if not text:
                    continue

                print(f"Indexing: {os.path.basename(f)}...")
                embedding = await engine.embed(text)

                if embedding:
                    self.cache["modules"][uid] = {
                        "hash": currentHash,
                        "embedding": embedding,
                        "name": os.path.splitext(os.path.basename(f))[0],
                        "path": f,
                    }
                    changed = True

        if changed:
            self._saveCache()
            print("Semantic index updated.")

    async def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """
        Search modules by natural language query.
        Returns a list of (module_path, similarity_score) tuples.
        """
        queryEmbedding = await engine.embed(query.lower())
        if not queryEmbedding:
            return []

        results = []
        for uid, data in self.cache["modules"].items():
            embedding = data.get("embedding")
            if embedding is None:
                continue
            
            score = engine.cosineSimilarity(queryEmbedding, embedding)
            results.append((uid, score))

        # get module files for results
        files = []
        for uid, score in results:
            path = UidManager.get(uid)
            if path:
                files.append((path, score))

        # Sort by score descending and return top_k
        files.sort(key=lambda x: x[1], reverse=True)
        return files[:k]
