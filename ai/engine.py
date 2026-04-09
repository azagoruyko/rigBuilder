import json
import shutil
import asyncio
import os
import ollama
from json_repair import repair_json

from ..settings import settings

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
OLLAMA_AVAILABLE = isOllamaAvailable()

# Global defaults
DEFAULT_MODEL = 'gpt-oss:20b-cloud'
CONTEXT_LIMIT = 8192

async def chat(messages: list, model: str = DEFAULT_MODEL, format: str = '', temperature: float = 0.0) -> str:
    """
    Asynchronous coroutine to communicate with Ollama.
    """
    if not OLLAMA_AVAILABLE:
        return ""

    additionalMessages = [
        {
            'role': 'system',
            'content': f'Translate all textual output to {settings.aiLanguage}. Do not translate code!'
        }
    ]

    try:
        response = await ollama.AsyncClient().chat(
            model=model,
            messages=additionalMessages + messages,
            format=format,
            options={'temperature': temperature}
        )
        return response.get('message', {}).get('content', '')
    except Exception as e:
        print(f"Ollama Async API Error: {e}")
        return ""

async def chatJSON(systemPrompt: str, userPrompt: str, model: str = DEFAULT_MODEL, temperature: float = 0.0) -> dict:
    """
    Asynchronous coroutine to communicate with Ollama expecting a JSON response. 
    Includes automatic JSON repair and parsing.
    """
    if not OLLAMA_AVAILABLE:
        return {}

    messages = [
        {'role': 'system', 'content': systemPrompt},
        {'role': 'user', 'content': userPrompt}
    ]
    
    resultText = await chat(messages, model=model, format='json', temperature=temperature)
    if not resultText:
        return {}

    try:
        # We use repair_json to handle common formatting errors
        repairedText = repair_json(resultText)
        return json.loads(repairedText)
    except Exception as e:
        print(f"Error decoding JSON from ollama response: {e}")
        return {}
