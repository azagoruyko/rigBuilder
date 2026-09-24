from __future__ import annotations

import json
import shutil
import asyncio
import os
import socket
import time
import ollama
from json_repair import repair_json

from ..core.settings import settings
from ..mcp_server.client import MCPClientManager

RootDirectory = os.path.dirname(__file__)
DEFAULT_CONTEXT_LIMIT = 8192
RESERVED_OUTPUT_TOKENS = 2048  # Reserved tokens for AI response generation
CHARS_PER_TOKEN = 2.4          # Character-to-token ratio for context budgeting

_ollamaAvailableCache = (False, 0.0) # (isAvailable, lastCheckTime)

def isOllamaAvailable(ttl: float = 5.0) -> bool:
    """Check if the Ollama server is reachable using a fast socket check with TTL caching."""
    global _ollamaAvailableCache
    status, lastCheck = _ollamaAvailableCache
    now = time.time()
    if now - lastCheck < ttl:
        return status

    available = False
    if shutil.which("ollama"):
        try:
            with socket.create_connection(("127.0.0.1", 11434), timeout=0.2):
                available = True
        except Exception:
            available = False

    _ollamaAvailableCache = (available, now)
    return available


with open(os.path.join(RootDirectory, '..', 'docs', 'tech.md'), 'r', encoding='utf-8') as f:
    TECH_DOCS = f.read()

with open(os.path.join(RootDirectory, 'prompt.md'), 'r', encoding='utf-8') as f:
    SYSTEM_PROMPT = '\n\n'.join([f.read(), TECH_DOCS])

_contextLimitCache = {}

def getContextLimit(model: str = None) -> int:
    """Get the context limit for a specific model from Ollama."""
    if model is None:
        model = settings.ollamaModel
    
    if model in _contextLimitCache:
        return _contextLimitCache[model]
    
    limit = DEFAULT_CONTEXT_LIMIT # Fallback
    try:
        info = ollama.show(model)
        modelinfo = getattr(info, 'modelinfo', {})
        # Look for keys like 'llama.context_length', 'gptoss.context_length', etc.
        for key, value in modelinfo.items():
            if key.endswith('.context_length'):
                limit = int(value)
                break
    except Exception as e:
        print(f"Error fetching context limit for {model}: {e}")
    
    _contextLimitCache[model] = limit
    return limit

def getMaxChars(model: str = None) -> int:
    """
    Get the estimated maximum character limit for input context based on token limit.
    Reserves tokens for output response generation.
    """
    contextTokens = getContextLimit(model)
    inputTokens = max(1024, contextTokens - RESERVED_OUTPUT_TOKENS)
    return int(inputTokens * CHARS_PER_TOKEN)


def pruneMessages(messages: list, maxChars: int = 250000) -> list:
    """Drop old user turns without splitting tool exchanges or truncating source code."""
    if not messages:
        return []

    turns = []
    for msg in messages:
        if not turns or msg.get('role') == 'user':
            turns.append([])

        turns[-1].append(msg)

    keptTurns = []
    currentChars = 0
    for turn in reversed(turns):
        turnChars = sum(len(json.dumps(msg, ensure_ascii=False)) for msg in turn)
        if currentChars + turnChars > maxChars:
            if not keptTurns:
                raise ValueError("The current request and tool results exceed the model context. Use a smaller selection or a model with a larger context.")

            break

        keptTurns.append(turn)
        currentChars += turnChars

    return [msg for turn in reversed(keptTurns) for msg in turn]


def getChatMessages(messages: list) -> list:
    """Prepare messages by injecting system prompts and pruning history."""
    systemMessages = [
        {
            'role': 'system',
            'content': SYSTEM_PROMPT
        },
        {
            'role': 'system',
            'content': f'Translate all textual output to {settings.aiLanguage}. Do not translate code!'
        }
    ]
    systemMessages.extend(msg for msg in messages if msg.get('role') == 'system')
    maxHeadroomChars = getMaxChars() - sum(len(json.dumps(msg, ensure_ascii=False)) for msg in systemMessages)
    pruned = pruneMessages([msg for msg in messages if msg.get('role') != 'system'], maxHeadroomChars)
    return systemMessages + pruned


async def chat(messages: list, format: str = '', temperature: float = 0.0) -> str:
    """
    Asynchronous coroutine to communicate with Ollama.
    """
    if not isOllamaAvailable():
        return ""

    contextLimit = getContextLimit()
    try:
        response = await ollama.AsyncClient().chat(
            model=settings.ollamaModel,
            messages=getChatMessages(messages),
            format=format,
            options={
                'temperature': temperature,
                'num_ctx': contextLimit
            }
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
    if not isOllamaAvailable():
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
    if not isOllamaAvailable():
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


def chatStreamWithTools(messages: list, temperature: float = 0.2, turnLimit: int = 5):
    """
    Generator that yields events from the chat loop with tools:
    ('chunk', content)
    ('tool_calls', list_of_tool_calls)
    ('tool_result', tool_msg_dict)
    ('stats', stats_dict)
    """
    totalMessages = getChatMessages(messages)
    tools = MCPClientManager.getOllamaTools()

    lastChunk = None
    
    for turn in range(turnLimit):
        # Guarantee totalMessages fits within context headroom on every turn loop
        userAndToolMsgs = [m for m in totalMessages if m.get('role') != 'system']
        totalMessages = getChatMessages(userAndToolMsgs)

        hasToolCalls = False
        currentToolCalls = []
        streamedContent = ""

        for chunk in ollama.chat(
            model=settings.ollamaModel,
            messages=totalMessages,
            stream=True,
            options={
                'temperature': temperature,
                'num_ctx': getContextLimit()
            },
            tools=tools
        ):
            lastChunk = chunk
            
            if isinstance(chunk, dict):
                msg = chunk.get('message', {})
                content = msg.get('content', '')
                tc = msg.get('tool_calls', [])
            else:
                msg = getattr(chunk, 'message', None)
                content = getattr(msg, 'content', '') if msg else ''
                tc = getattr(msg, 'tool_calls', []) if msg else []
            
            if tc:
                hasToolCalls = True
                for call in tc:
                    if isinstance(call, dict):
                        currentToolCalls.append(call)
                    else:
                        func_obj = getattr(call, 'function', None)
                        funcName = getattr(func_obj, 'name', None)
                        args = getattr(func_obj, 'arguments', {})
                        currentToolCalls.append({
                            'function': {
                                'name': funcName,
                                'arguments': args
                            }
                        })
            
            if content:
                streamedContent += content
                yield ('chunk', content)
                
        if hasToolCalls:
            assistantMsg = {
                'role': 'assistant',
                'content': streamedContent,
                'tool_calls': currentToolCalls
            }
            totalMessages.append(assistantMsg)
            yield ('tool_calls', currentToolCalls)
            
            for call in currentToolCalls:
                if isinstance(call, dict):
                    funcName = call.get('function', {}).get('name')
                    args = call.get('function', {}).get('arguments', {})
                else:
                    funcName = getattr(getattr(call, 'function', None), 'name', None)
                    args = getattr(getattr(call, 'function', None), 'arguments', {})

                if funcName:
                    result = MCPClientManager.executeTool(funcName, args)
                    
                    resStr = str(result)
                    toolMsg = {
                        'role': 'tool',
                        'content': resStr,
                        'name': funcName
                    }
                    totalMessages.append(toolMsg)
                    yield ('tool_result', toolMsg)
                    
            continue # Re-run chat with new tool messages
        else:
            break # No tool calls, finish

    stats = {}
    if lastChunk:
        statKeys = ['total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration', 'eval_count', 'eval_duration']
        if isinstance(lastChunk, dict):
            stats = {k: lastChunk.get(k) for k in statKeys if k in lastChunk}
        else:
            stats = {k: getattr(lastChunk, k, None) for k in statKeys if hasattr(lastChunk, k)}

    yield ('stats', stats)
