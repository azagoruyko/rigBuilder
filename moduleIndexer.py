import os
import json
import hashlib
import xml.etree.ElementTree as ET
from typing import List, Tuple, Dict, Any

from . import core
from .ai import engine
from .settings import RIG_BUILDER_USER_PATH, settings

INDEX_FILE = os.path.join(RIG_BUILDER_USER_PATH, "moduleIndex.json")

class ModuleIndexer:
    """
    Handles indexing of rigging modules and semantic search using vector embeddings.
    """
    def __init__(self):
        self.cache: Dict[str, Any] = self._loadCache()

    def _loadCache(self) -> Dict[str, Any]:
        """Load the index cache from disk."""
        if os.path.exists(INDEX_FILE):
            try:
                with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading index cache: {e}")
        return {"modules": {}}

    def _saveCache(self):
        """Save the index cache to disk."""
        os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
        try:
            with open(INDEX_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=4)
        except Exception as e:
            print(f"Error saving index cache: {e}")

    def _getFileHash(self, filePath: str) -> str:
        """Calculate MD5 hash of a file."""
        hasher = hashlib.md5()
        with open(filePath, 'rb') as f:
            buf = f.read()
            hasher.update(buf)
        return hasher.hexdigest()

    def _extractIndexableText(self, filePath: str) -> str:
        """Extract name, docs, and attributes labels for indexing."""
        try:
            tree = ET.parse(filePath)
            root = tree.getroot()
            
            name = root.attrib.get("name", os.path.splitext(os.path.basename(filePath))[0])
            doc = ""
            doc_el = root.find("doc")
            if doc_el is not None:
                doc = doc_el.text or ""

            # Get the first paragraph or generic description for context
            summary = doc.split("\n\n")[0] if "\n\n" in doc else doc

            # Extract attribute names/labels to help with keyword matching
            attrs = []
            attrs_el = root.find("attributes")
            if attrs_el is not None:
                for attr in attrs_el.findall("attr"):
                    attr_name = attr.attrib.get("name", "")
                    if attr_name:
                        attrs.append(attr_name)
            
            attr_text = ", ".join(attrs)
            
            # Construct a rich payload for embedding
            return f"Module: {name}. Summary: {summary}. Keywords: {attr_text}. Full help: {doc}"
        except Exception as e:
            print(f"Error extracting text from {filePath}: {e}")
            return ""

    async def indexModules(self, force: bool = False):
        """
        Walks through the modules directory and generates embeddings for new/changed files.
        """
        moduleFiles = core.Module.listModules(settings.modulesPath)
        changed = False

        for f in moduleFiles:
            abs_path = os.path.abspath(f)
            current_hash = self._getFileHash(abs_path)
            
            cached_data = self.cache["modules"].get(abs_path)
            
            # Index if forced, or hash changed, or never indexed
            if force or not cached_data or cached_data.get("hash") != current_hash:
                print(f"Indexing: {os.path.basename(f)}...")
                text = self._extractIndexableText(abs_path)
                if not text:
                    continue
                    
                embedding = await engine.embed(text)
                if embedding:
                    self.cache["modules"][abs_path] = {
                        "hash": current_hash,
                        "embedding": embedding,
                        "name": os.path.splitext(os.path.basename(f))[0]
                    }
                    changed = True
        
        if changed:
            self._saveCache()
            print("Semantic index updated.")
        else:
            print("Semantic index is up to date.")

    async def search(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        Search modules by natural language query.
        Returns a list of (module_path, similarity_score) tuples.
        """
        query_embedding = await engine.embed(query)
        if not query_embedding:
            return []

        results = []
        for path, data in self.cache["modules"].items():
            score = engine.cosineSimilarity(query_embedding, data["embedding"])
            results.append((path, score))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]
