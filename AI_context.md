# Rig Builder Technical Notes for AI

This file is a compact contract for AI-assisted editing of Rig Builder modules and related Python code.

Use it when generating or modifying modules, attributes, connections, run code, or widget/template data.

In external-editor workflow, this file is copied into the working folder and acts as the authoritative AI guidance for that edit session.

## 1) Core Model

- Rig Builder is host-agnostic. A module should rely on API/context symbols, not direct host imports.
- A module is a node with:
  - metadata (`name`, `uid`, `muted`, etc.),
  - `run` code (Python),
  - attributes (name/category/template/connect/expression/data),
  - children (nested modules).
- Execution is hierarchical: parent module runs first, then children (unless muted/failed).
- Attribute expressions and module run code execute in a context dictionary (API + module helpers + attr values).

## 2) Attribute Semantics (Critical)

Each attribute stores:

- `template`: widget/template type (for editor/UI behavior).
- `data`: JSON-like payload for that template.
- `default`: key inside `data` that points to the primary value.

Important behavior:

- `Attribute.get()` resolves from `data[data["default"]]` (after pull/expression flow).
- `Attribute.set(value)` updates the default value then pushes connections.
- `Attribute.data()` returns a defensive copy.
- `Attribute.setData(...)` updates local payload and propagates when required.

Do not break:

- the `default` key,
- expected data keys for the selected template,
- JSON-serializable structure for XML persistence.

## 3) Widget/Template Data Rules

Widget templates serialize to dict payloads. Common patterns:

- check box: `{"checked": bool, "default": "checked"}`
- combo: `{"items": [...], "current": value, "default": "current"}`
- text/label: `{"text": str, "default": "text"}`
- list/table/json-like templates keep container keys (`items`, `header`, `data`, etc.) plus `default`.
- lineEditAndButton: `value` is the edit-line value; the button can run a specific command (e.g. get selected node, open file dialog). Typical keys: `value`, `buttonCommand`, `buttonLabel`, `buttonEnabled`, `min`, `max`, `validator` (0: none, 1: int, 2: double).
For button commands you can use `import rigBuilder.qt` to access Qt.

Guidelines for AI edits:

- Preserve unknown keys when modifying template payloads.
- Update only keys needed for requested behavior.

## 4) Run Code Authoring Rules

- Write deterministic, explicit Python.
- Use provided context/API functions rather than direct DCC calls when possible.
- Avoid hidden global state and import-time side effects.
- Keep module behavior local and predictable.
- Handle missing/empty attribute values defensively.

Preferred flow:

1. Read inputs from attributes/context.
2. Validate/coerce.
3. Perform operation.
4. Write results back through attribute/API helpers.

Round-trip notes:

- In canonical module code, attributes are referenced as `@attrName`.
- In exported run code file, attribute names are rewritten to `attr_attrName` (`ATTR_PREFIX + name`).
- On import back, `attr_attrName` is rewritten to `@attrName`.
- Keep the generated predef import as the first line of exported run code file.

Attribute references:

- Prefer `@attrName` (or `attr_attrName` in exported editor files) over the `ch` function for the current module.

## 5) Host-Agnostic Policy

Rig Builder can run in Maya, Blender, or standalone contexts.

- Core Rig Builder architecture should stay host-agnostic.
- Modules themselves may be host-specific and can use direct host imports (for example, `import maya.cmds as cmds`) when intended for that host.
- If a module is intended to be reusable across hosts, prefer context/API abstractions over direct host imports.

## 6) XML and Persistence Safety

Modules/attributes are stored in XML, with run code in CDATA and attribute data as JSON text.

AI changes must preserve:

- valid XML-serializable string content,
- JSON-serializable attribute payloads,
- stable attribute/template contracts expected by UI loaders.

Avoid introducing payload objects that cannot be serialized.

External-editor XML specifics:

- Expect module XML file to represent only the selected module itself.
- Do not assume child hierarchy can be edited via exported XML in this workflow.
- Keep XML consistent with module-level metadata + attributes only.

## 7) Style and Refactoring Constraints

- Follow local project style from surrounding files.
- Use DCC coding style once DCC is recognized via imports or coding patterns.
- Do not introduce new abstractions or concepts unless explicitly requested.
- Avoid splitting logic into tiny redundant functions.
- Keep comments concise and in English.

## 8) AI Output Checklist

Before finalizing generated module edits:

1. Preserves attribute payload schema, especially `default`.
2. Keeps run code and module XML responsibilities separated.
3. Does not expect child editing through exported XML.
4. Avoids host-locked imports in generic modules unless module is intentionally host-specific.
5. Maintains serialization safety (XML/JSON).
6. Changes only requested behavior.

## 9) On-the-Fly Module Construction Protocol

Use this protocol when AI must construct a Rig Builder module tree from a task description.

Step order matters:

1. Define root module intent:
  - Name the root by outcome, not implementation detail.
  - Keep run code minimal and orchestrative.
2. Define attributes for each module:
  - For every input/output/control, create an explicit attribute.
  - Pick template + payload matching value type and UI intent.
  - Ensure each payload has a valid `default` key.
3. Write run code:
  - Read from local attributes/context.
  - Perform deterministic work.
  - Emit results to attributes/API helpers used by downstream modules.
4. Validate persistence:
  - Confirm all attribute payloads are JSON-serializable.
  - Confirm run code and doc text are XML-safe.

## 10) Children and Connection Rules

- Avoid adding children to the module. It's not supported to edit as the module must be self-contained.
- Avoid changing connections for attributes.

## 11) Attribute Authoring Heuristics

- Scalar toggles: `checkBox`.
- Enumerated choices: `comboBox` with explicit `items`.
- Free text/numbers: `lineEditAndButton` with typed defaults.
- Collections: `listBox` / table-like templates.
- Structured payloads: `json`.
- Keep `category` meaningful (`General`, `Build`, `Debug`, etc.) for UI readability.

## 12) Editing in External Editor

`editInVSCode()` exports and tracks three files per selected module:

- `*_predef.py`: generated context stubs (attributes + API values/functions).
- `<module>.py`: editable run code file.
- `<module>.xml`: editable self-contained module definition.

Important behavior:

- Run code is stored separately from module XML during external editing.
- Exported XML is intentionally self-contained:
  - run code is cleared in XML export,
  - children are removed from XML export.
- Child modules stay in Rig Builder tree and are not part of external XML editing.
- `AI_context.md` is copied into the same external editor folder for prompt context.
- Rig Builder watches both editable files:
  - changes in `<module>.py` update module run code,
  - changes in `<module>.xml` replace current module data (children are reattached from tree state).

Predef is generated from current module state and execution context.

Generated predef usually exposes:

- `attr_<name>`: current attribute value snapshot.
- `attr_set_<name>(value)`: setter helper signature.
- `attr_<name>_data`: full JSON-like data payload for the attribute.
- Context/API symbols from module environment:
  - callables emitted as signature stubs,
  - serializable values emitted as literals,
  - non-serializable values may be absent or `None`.

Guidelines:

- Treat predef as typing/autocomplete aid, not canonical runtime truth.
- Do not manually edit generated predef files.
- Validate optional/nullable predef values before use.

