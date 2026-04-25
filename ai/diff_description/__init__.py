import os
import sys
from .. import engine

# Load the system prompt for diff analysis
promptFile = os.path.join(os.path.dirname(__file__), "prompt.md")
with open(promptFile, "r", encoding="utf-8") as f:
    systemPrompt = f.read()

async def run(inputText: str) -> str:
    """
    Asynchronous function to analyze a diff patch and return a brief description.
    """
    limit = engine.getMaxChars()
    if len(inputText) > limit:
        inputText = inputText[:limit]

    if "{{diff}}" in systemPrompt:
        formattedPrompt = systemPrompt.replace("{{diff}}", inputText)
        messages = [
            {'role': 'user', 'content': formattedPrompt}
        ]
    else:
        messages = [
            {'role': 'system', 'content': systemPrompt},
            {'role': 'user', 'content': f"Analyze this diff:\n\n{inputText}"}
        ]

    return await engine.chat(messages)
