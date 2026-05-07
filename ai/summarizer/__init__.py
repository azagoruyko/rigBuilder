import os
from .. import engine

PROMPT_FILE = os.path.join(os.path.dirname(__file__), 'prompt.md')

with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
    PROMPT_TEMPLATE = f.read()

async def run(inputText: str) -> str:
    """
    Synthesizes multiple summaries or descriptions into one.
    """
    summary = await engine.chat(
        messages=[
            {'role': 'system', 'content': PROMPT_TEMPLATE.strip()},
            {'role': 'user', 'content': inputText}
        ]
    )
    return summary or "Could not generate synthesis."


