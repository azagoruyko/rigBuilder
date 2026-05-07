import os
from .. import engine

PROMPT_FILE = os.path.join(os.path.dirname(__file__), 'prompt.md')

with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
    PROMPT_TEMPLATE = f.read()

async def run(inputText: str) -> str:
    """
    Generates module-specific documentation by synthesizing code analysis and child docs.
    """
    summary = await engine.chat(
        messages=[
            {'role': 'system', 'content': PROMPT_TEMPLATE.strip()},
            {'role': 'user', 'content': inputText}
        ]
    )
    return summary or "Could not generate documentation."


