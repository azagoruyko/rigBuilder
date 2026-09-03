from __future__ import annotations

import os
import re
import json
import xml.etree.ElementTree as ET
from typing import Any

from . import core
from .uidManager import UidManager
from ..ai import engine
from .settings import settings
from .utils import loadJson, saveJson, fileHash

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
        if settings.modulesPath and filePath.startswith(settings.modulesPath):
            relDir = os.path.dirname(os.path.relpath(filePath, settings.modulesPath)).replace("\\", "/")
            if relDir and relDir != ".":
                category = relDir

        # Extract first section (preamble or text under first header)
        sections = re.split(r'\n(?=#{1,6}\s+)', doc)
        firstSection = re.sub(r'^#{1,6}\s+.*\n?', '', sections[0]) if sections else ""

        # Clean code blocks, formatting symbols, and extra whitespace
        firstSection = re.sub(r'```[\s\S]*?```', '', firstSection)
        cleanSummary = re.sub(r'\s+', ' ', re.sub(r'[*_`#]', '', firstSection)).strip()

        return f"Module: {m.name()}. Category: {category}. Summary: {cleanSummary}"

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
            if not engine.isOllamaAvailable():
                print(f"Note: Current embedding model ({currentModel}) differs from the index ({cachedModel}).")
                print("Re-indexing is pending until Ollama is available.")
            else:
                print(f"Embedding model mismatch ({cachedModel} -> {currentModel}). Forcing full re-index...")
                self.cache["model"] = currentModel
                self.cache["modules"] = {} # Clear old embeddings
                changed = True
                force = True # Force re-indexing of all files

        if not engine.isOllamaAvailable():
            if changed:
                self._saveCache() # Save if we just initialized the model name
            return

        moduleFiles = core.Module.listModules(folder)

        for f in moduleFiles:
            currentHash = fileHash(f)
            uid = UidManager.getUidFromFile(f)
            if not uid:
                continue

            cachedData = self.cache["modules"].get(uid)
            
            # Index if forced, or hash changed, or never indexed
            if force or not cachedData or cachedData.get("hash") != currentHash:
                text = self._extractIndexableText(f)
                if not text:
                    continue

                print(f"Indexing: {os.path.basename(f)}...")
                embedding = await engine.embed(text)

                if embedding:
                    self.cache["modules"][uid] = {
                        "hash": currentHash,
                        "embedding": embedding,
                        "name": os.path.splitext(os.path.basename(f))[0]
                    }
                    changed = True

        # remove older files from cache
        for uid in list(self.cache["modules"].keys()):            
            if uid not in UidManager.uids():
                del self.cache["modules"][uid]
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
            files.append((path, score))

        # Sort by score descending and return top_k
        files.sort(key=lambda x: x[1], reverse=True)
        return files[:k]
