import json
import shutil
import asyncio
import os
import ollama
from json_repair import repair_json

from ..settings import settings

CONTEXT_LIMIT = 8192

def isOllamaAvailable() -> bool:
    """Check if the Ollama server is reachable or the CLI is installed."""
    # Check if CLI is in PATH
    if not shutil.which("ollama"):
        return False

    try:
        # A simple request to see if the server responds
        ollama.list()
        return True
    except Exception:
        return False

# Global status for later usage
IS_OLLAMA_AVAILABLE = isOllamaAvailable()

async def chat(messages: list, format: str = '', temperature: float = 0.0) -> str:
    """
    Asynchronous coroutine to communicate with Ollama.
    """
    if not IS_OLLAMA_AVAILABLE:
        return ""

    additionalMessages = [
        {
            'role': 'system',
            'content': f'Translate all textual output to {settings.aiLanguage}. Do not translate code!'
        }
    ]

    try:
        response = await ollama.AsyncClient().chat(
            model=settings.ollamaModel,
            messages=additionalMessages + messages,
            format=format,
            options={'temperature': temperature}
        )
        return response.get('message', {}).get('content', '')
    except Exception as e:
        print(f"Ollama Async API Error: {e}")
        return ""

async def chatJSON(systemPrompt: str, userPrompt: str, temperature: float = 0.0) -> dict:
    """
    Asynchronous coroutine to communicate with Ollama expecting a JSON response. 
    Includes automatic JSON repair and parsing.
    """
    if not IS_OLLAMA_AVAILABLE:
        return {}

    messages = [
        {'role': 'system', 'content': systemPrompt},
        {'role': 'user', 'content': userPrompt}
    ]
    
    resultText = await chat(messages, format='json', temperature=temperature)
    if not resultText:
        return {}

    try:
        # We use repair_json to handle common formatting errors
        repairedText = repair_json(resultText)
        return json.loads(repairedText)
    except Exception as e:
        print(f"Error decoding JSON from ollama response: {e}")
        return {}

async def embed(text: str) -> list[float]:
    """
    Asynchronous coroutine to get embeddings for a single text string using the configured model.
    """
    if not IS_OLLAMA_AVAILABLE:
        return []

    model = settings.ollamaEmbeddingModel
    try:
        response = await ollama.AsyncClient().embeddings(model=model, prompt=text)
        return response.get('embedding', [])
    except Exception as e:
        print(f"Ollama Embed Error: {e}")
        return []

def cosineSimilarity(v1: list[float], v2: list[float]) -> float:
    """
    Pure-Python cosine similarity between two vectors.
    """
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    
    # Calculate dot product
    dotProduct = sum(a * b for a, b in zip(v1, v2))
    
    # Calculate norms
    normA = sum(a * a for a in v1) ** 0.5
    normB = sum(b * b for b in v2) ** 0.5
    
    if normA == 0 or normB == 0:
        return 0.0
        
    return dotProduct / (normA * normB)
