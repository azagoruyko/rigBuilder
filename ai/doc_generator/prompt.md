# Module Documentation Generator

Your task is to analyze a module's code and its children's documentation to generate cohesive, structured documentation for the module.

## Instructions

1. **Module Inputs**: Identify key inputs expected by the module. Reference the relevant attribute/parameter names (e.g., **`joint1`**, **`joint2`**, **`joint3`**) and explain their concrete functional role (what scene objects, data, or settings they expect).
2. **Module Outputs**: Identify what the module generates and outputs. Reference the relevant output attribute/node names (e.g., **`out_ikCtrl`**, **`moduleInfo`**) and explain what rig controls, joint chains, or data containers they produce for downstream modules.
3. **Synthesize Summary**: Provide a clear 1-3 sentence summary of what the module is doing.
4. **Provide Usage Instructions**: Detail practical steps on how to configure and execute the module (e.g., mode switching, helper workflows, downstream connections).
5. **Structure**: Always format the output using the exact four headers: `## Summary`, `## Inputs`, `## Outputs`, `## Usage`.
6. **No Outer Code Blocks**: Do NOT wrap your output in markdown code blocks (` ```markdown ` or ` ``` `). Output raw Markdown directly.

## Output Format

Example of output you should generate:

```markdown
## Summary
Builds a 3-joint IK/FK limb rig system (such as arms or legs) with configurable helper placement, IK/FK switching, stretch, soft IK, and automated mirror symmetry setup.

## Inputs
- **Limb Joint Chain (`joint1`, `joint2`, `joint3`)**: Names of the 3 target joints forming the limb skeleton (e.g. shoulder, elbow, wrist).
- **Placement Helpers (`h_fk1..3`, `h_ik`, `h_polevector`, `h_options`)**: Guide transform nodes created in `Helpers` mode to position controls in the scene.
- **End Control Orientation (`lastCtrlOrient`)**: Reference joint/node used to orient the wrist or ankle control.
- **IK Helper Shape (`ikHelperType`)**: Shape design for the IK control curve (cube, sphere, diamond, etc.).
- **Execution Mode (`mode`)**: Toggles between `Helpers` (generate placement guides) and `Run` (build final rig).

## Outputs
- **Rig Controllers (`out_ikCtrl`, `out_polevecCtrl`, `out_ikfkSwitch`)**: Generated IK control, pole vector control, and IK/FK blend switch node.
- **Limb Joint Chains (`out_fk1..3`, `out_ik1..3`)**: Generated FK and IK joint hierarchies driven by the main limb logic.
- **IK Handles (`out_ikHandle`, `out_fix2_ikHandle`)**: Single-chain IK handles driving the joint solver.
- **Pipeline Interface (`moduleInfo`)**: Published container node registering all generated controls and joints so downstream modules (e.g. hand or foot) can attach to them.

## Usage
- Specify target joints (`joint1`, `joint2`, `joint3`) and run in `Helpers` mode to create placement guide controls.
- Adjust helper shapes and positions in the Maya viewport to match character anatomy.
- Switch to `Run` mode and execute to build the complete IK/FK limb setup.
- Connect the generated `moduleInfo` or output nodes to child modules (such as hand, foot, or finger rigs).
```

## Input

Below is the input for the prompt.