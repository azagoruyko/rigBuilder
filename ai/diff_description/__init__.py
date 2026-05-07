import os
import sys
from .. import engine

PROMPT_FILE = os.path.join(os.path.dirname(__file__), "prompt.md")
with open(PROMPT_FILE, "r", encoding="utf-8") as f:
    PROMPT_TEMPLATE = f.read()

async def run(inputText: str) -> str:
    """
    Asynchronous function to analyze a diff patch and return a brief description.
    """
    limit = engine.getMaxChars()
    if len(inputText) > limit:
        inputText = inputText[:limit]

    return await engine.chat(
        messages=[
            {'role': 'system', 'content': PROMPT_TEMPLATE.strip()},
            {'role': 'user', 'content': f"Analyze this diff:\n\n{inputText}"}
        ]
    )

