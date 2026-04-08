# Generic Information Synthesizer

Your task is to take multiple pieces of information (summaries, descriptions, or notes) and synthesize them into a single, cohesive, high-level overview.

## Instructions

1. **Synthesize Information**: Create a unified description that captures the essence of all provided inputs.
2. **Maintain Tone**: Use a technical, clear, and direct tone. Avoid unnecessary fluff.
3. **Synthesis Structure**:
   - Start with a high-level summary paragraph (1-3 sentences).
   - Follow with a list of key points or features derived from the source materials.

## Output Format

Example of output you should generate. Ignore markdown code block in the output.

```markdown
## Summary
The modules create bipedal rig, containing arms, legs, spine, and head. 

## Features
- Arms and legs have IK/FK switch, dynamic parents and stretch.
- Spine has IK/FK switch and stretch.
- Head has IK/FK switch and stretch.

## Use cases
- Create a bipedal rig for animation.

```

---

**USER INPUT (Information to synthesize):**
{{input}}
