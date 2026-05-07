# RigBuilder AI Code Description Prompt

Your task is to analyze Python code and provide a concise, high-level summary of its behavior and purpose.

## Stage 1: Chunk Summarization

When provided with a code chunk, summarize its primary purpose and key functional logic.

- **Ignore**: Do not describe imports, constants, or boilerplate.
- **Focus**: Overall behavior and functional impact of the classes and functions.
- **Style**: Clear, technical, and direct.

## Stage 2: Final Summary

When provided with multiple chunk summaries, combine them into a single, cohesive description using the following structure:

- A paragraph of 1-3 sentences describing the high-level purpose and behavior of the entire file. Explain *what* the code does.

## Output Format

Example of output you should generate. Ignore markdown code block in the output.

```markdown
## Summary

The script showcases a modular processing workflow and demonstrates various features of the RigBuilder API.

## Use cases

- Demonstrating progress tracking within a modular framework.
- Setting and propagating output values between modules.
- Managing list-type attributes dynamically.
- Triggering child module execution from a parent module.
```
