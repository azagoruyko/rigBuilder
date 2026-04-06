from typing import Union
from . import code_description
from . import diff_description
from . import diff_summary
from . import variable_extraction

async def run(command: str, inputText: str) -> Union[str, dict]:
    """
    Unified entry point for AI commands.
    
    Args:
        command: The command name (e.g., 'code_description', 'diff_summary', etc.)
        inputText: The input text to process.
        
    Returns:
        Union[str, dict]: The result of the AI command.
    """
    commands = {
        "code_description": code_description.run,
        "diff_description": diff_description.run,
        "diff_summary": diff_summary.run,
        "variable_extraction": variable_extraction.run,
    }
    
    if command not in commands:
        raise ValueError(f"Unknown AI command: {command}")
        
    return await commands[command](inputText)
