# Context Compactor

Compress and synthesize the provided content into a compact, high-signal summary while preserving the most important meaning, context, structure, and distinguishing details.

The input may contain:
- Text
- Conversations
- Documentation
- Notes
- Articles
- Logs
- Technical content
- Mixed content

## Instructions

### Preserve
- Core ideas and intent
- Important facts and details
- Key relationships and structure
- Decisions, constraints, and assumptions
- Important reasoning or conclusions
- Unique insights or characteristics
- Technical terminology when relevant
- Tone or style only if important to meaning

### Remove or Compress
- Repetition
- Filler
- Small talk
- Redundant explanations
- Decorative wording
- Low-value details

### Output Requirements
- Use concise, information-dense markdown
- Prefer bullet points and structure over prose
- Preserve nuance and critical context
- Do not invent information
- Do not omit important meaning

## Output Format

```markdown
# Summary

## Core Idea
Short high-level synthesis.

## Key Points
- Point
- Point

## Important Details
- Constraints
- Decisions
- Relationships
- Notable context

## Open Questions / Risks
- Remaining uncertainty
- Potential issues
```

## Goal

Maximize retained meaning and useful context per token.

## Input

Below is the input for the prompt.