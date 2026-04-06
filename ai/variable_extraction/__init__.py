import os
import sys
import json
from .. import engine

# Load the system prompt for variable extraction
PROMPT_FILE = os.path.join(os.path.dirname(__file__), "prompt.md")
with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

async def run(inputText: str) -> dict:
    """
    Extracts global variables and function arguments from a script.
    """
    # Truncate to context limit
    if len(inputText) > engine.CONTEXT_LIMIT:
        inputText = inputText[:engine.CONTEXT_LIMIT]
        
    userPrompt = f"Analyze the following Python script:\n\n{inputText}"
    return await engine.chatJSON(SYSTEM_PROMPT, userPrompt)
