import os
import sys
from .. import engine

PROMPT_FILE = os.path.join(os.path.dirname(__file__), 'prompt.md')
MAX_CHUNK_SIZE = engine.CONTEXT_LIMIT

def loadPrompt():
    if not os.path.exists(PROMPT_FILE):
        return "Summarize the following Python code:\n{{input}}"
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        return f.read()

def getChunks(code, maxChars=MAX_CHUNK_SIZE):
    """
    Splits Python code into logical chunks.
    Identifies logical blocks (def, class, if, for, etc.) using indentation.
    """
    lines = code.splitlines()
    chunks = []
    currentChunkLines = []
    currentLen = 0
    
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        
        # Keep empty lines and comments
        if not stripped or stripped.startswith('#'):
            currentChunkLines.append(line)
            currentLen += len(line) + 1
            i += 1
            continue
            
        # Detect block start at current indentation
        indent = len(line) - len(stripped)
        keywords = ('def ', 'class ', 'if ', 'for ', 'while ', 'try ', 'with ', 'elif ', 'else:', 'except ')
        isBlockStart = any(stripped.startswith(k) for k in keywords)
        
        if isBlockStart:
            # Capture the full block (lines with higher indentation)
            blockLines = [line]
            j = i + 1
            while j < len(lines):
                nextStripped = lines[j].lstrip()
                if not nextStripped or nextStripped.startswith('#'): 
                    blockLines.append(lines[j])
                    j += 1
                    continue
                
                nextIndent = len(lines[j]) - len(nextStripped)
                if nextIndent > indent:
                    blockLines.append(lines[j])
                    j += 1
                else:
                    break
            
            blockText = "\n".join(blockLines)
            blockLen = len(blockText)
            
            if currentLen + blockLen > maxChars and currentChunkLines:
                chunks.append("\n".join(currentChunkLines).strip())
                currentChunkLines = blockLines
                currentLen = blockLen
            else:
                currentChunkLines.extend(blockLines)
                currentLen += blockLen + 1
            i = j
        else:
            if currentLen + len(line) > maxChars and currentChunkLines:
                chunks.append("\n".join(currentChunkLines).strip())
                currentChunkLines = [line]
                currentLen = len(line)
            else:
                currentChunkLines.append(line)
                currentLen += len(line) + 1
            i += 1
            
    if currentChunkLines:
        text = "\n".join(currentChunkLines).strip()
        if text:
            chunks.append(text)
        
    return chunks

async def run(inputText) -> str:
    """
    Asynchronous function to summarize the code in two stages.
    """
    promptTemplate = loadPrompt()
    chunks = getChunks(inputText)
    
    # Stage 1: Summarize Chunks
    chunkSummaries = []
    systemPrompt = promptTemplate.split("---")[0].strip()

    for i, chunk in enumerate(chunks):
        print(f"Summarizing chunk {i+1}/{len(chunks)}...")
        summary = await engine.chat(
            messages=[
                {'role': 'system', 'content': f"{systemPrompt}\n\nTask: Summarize this portion of the code."},
                {'role': 'user', 'content': chunk}
            ]
        )
        if summary:
            chunkSummaries.append(summary)

    if not chunkSummaries:
        return "Could not generate summary."

    # Stage 2: Final Summary
    combinedSummaries = "\n\n".join(chunkSummaries)
    print("Generating final overall summary...")
    
    finalSummary = await engine.chat(
        messages=[
            {'role': 'system', 'content': f"{systemPrompt}\n\nTask: Combine these chunk summaries into one cohesive description."},
            {'role': 'user', 'content': combinedSummaries}
        ]
    )
    
    return finalSummary
