import os
from .. import engine

PROMPT_FILE = os.path.join(os.path.dirname(__file__), 'prompt.md')

def loadPrompt():
    if not os.path.exists(PROMPT_FILE):
        return "Synthesize the following information:\n{{input}}"
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        return f.read()

async def run(inputText: str) -> str:
    """
    Synthesizes multiple summaries or descriptions into one.
    """
    promptTemplate = loadPrompt()
    systemPrompt = promptTemplate.split("---")[0].strip()
    
    summary = await engine.chat(
        messages=[
            {'role': 'system', 'content': systemPrompt},
            {'role': 'user', 'content': inputText}
        ]
    )
    
    return summary or "Could not generate synthesis."
