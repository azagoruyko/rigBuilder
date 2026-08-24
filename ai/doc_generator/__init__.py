import os
from .. import engine

PROMPT_FILE = os.path.join(os.path.dirname(__file__), 'prompt.md')

with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
    PROMPT_TEMPLATE = f.read()


def getChunks(text: str, maxChars: int = None):
    """
    Splits input text/code into logical chunks based on block structure and max limit.
    """
    if maxChars is None:
        maxChars = engine.getMaxChars()

    lines = text.splitlines()
    chunks = []
    currentChunkLines = []
    currentLen = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if not stripped or stripped.startswith('#'):
            currentChunkLines.append(line)
            currentLen += len(line) + 1
            i += 1
            continue

        indent = len(line) - len(stripped)
        keywords = ('def ', 'class ', 'if ', 'for ', 'while ', 'try ', 'with ', 'elif ', 'else:', 'except ')
        isBlockStart = any(stripped.startswith(k) for k in keywords)

        if isBlockStart:
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
        t = "\n".join(currentChunkLines).strip()
        if t:
            chunks.append(t)

    return chunks


def stripCodeBlocks(text: str) -> str:
    """Strips outer markdown code block delimiters if present."""
    if not text:
        return text
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


async def run(inputText: str) -> str:
    """
    Generates module documentation by analyzing code and child docs.
    Supports chunking if input size exceeds max character limits.
    """
    if not inputText or not inputText.strip():
        return "Could not generate documentation."

    chunks = getChunks(inputText)

    if len(chunks) <= 1:
        print("Generating documentation...")
        summary = await engine.chat(
            messages=[
                {'role': 'system', 'content': PROMPT_TEMPLATE.strip()},
                {'role': 'user', 'content': inputText}
            ]
        )
        return stripCodeBlocks(summary) if summary else "Could not generate documentation."

    # Multi-chunk processing: summarize each chunk, then synthesize into final doc
    chunkSummaries = []
    for i, chunk in enumerate(chunks):
        print(f"Summarizing chunk {i+1}/{len(chunks)}...")
        chunkSummary = await engine.chat(
            messages=[
                {'role': 'system', 'content': "Analyze this portion of code/documentation and describe its functional purpose, inputs used, and outputs generated."},
                {'role': 'user', 'content': chunk}
            ]
        )
        if chunkSummary:
            chunkSummaries.append(f"### Chunk {i+1} Summary\n{chunkSummary}")

    combinedText = "\n\n".join(chunkSummaries)
    print("Generating final overall documentation...")
    summary = await engine.chat(
        messages=[
            {'role': 'system', 'content': PROMPT_TEMPLATE.strip()},
            {'role': 'user', 'content': combinedText}
        ]
    )
    return stripCodeBlocks(summary) if summary else "Could not generate documentation."
