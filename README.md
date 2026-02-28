# RigBuilder

<div>
<img src="https://img.shields.io/github/v/release/azagoruyko/rigBuilder?logoColor=green&color=green"/>
<a href="https://github.com/azagoruyko/rigBuilder/wiki/Documentation">
  <img src="https://img.shields.io/badge/docs-here-blue?label=docs"/>
</a>
</div>

RigBuilder is a Qt-based visual builder for Python tooling, with a strong focus on DCC workflows (Maya by default).

It combines:

- a tree-based module system (`core.py`) with XML serialization,
- a full editor/runtime UI (`ui.py`),
- and a live Python function browser (`functionBrowser.py`) that auto-builds argument widgets from function signatures.

<img width="1294" height="916" alt="image" src="https://github.com/user-attachments/assets/f47a27a8-57c5-4f32-b118-9ef77d513796" />

## Current capabilities

- Build hierarchical tools from modules and run them with progress + logging.
- Store module definitions as XML files and reload/update them by UID.
- Connect attributes between modules (`/path/to/attr` style references).
- Execute per-attribute expressions and module-level Python code.
- Launch a Function Browser to discover and run Python functions from a folder.
- Run in Maya or standalone with either `PySide2` or `PySide6` (based on what is available).

## Runtime modes

### Maya mode (default)

If `RIG_BUILDER_DCC` is not set, the UI assumes Maya mode and imports `maya.cmds` APIs.

Typical launch inside Maya:

```python
import rigBuilder.ui
rigBuilder.ui.mainWindow.show()
```

### Standalone mode

Use `run.py`, which sets `RIG_BUILDER_DCC=standalone` before loading the UI:

```bash
python run.py
```

## Dependencies

From `requirements.txt`:

- `PySide6>=6.0.0` (default standalone dependency in this repo)
- `pytest>=7.0.0`
- `pytest-cov>=4.0.0`

Notes:

- In Maya, `PySide2` is usually provided by the host application.
- Standalone can use either `PySide2` or `PySide6`; `qt.py` tries `PySide2` first, then falls back to `PySide6`.
- `requirements.txt` pins `PySide6` for convenience, but standalone is not limited to it.

## Module locations

- Built-in modules: `modules/`
- Local user modules: `%USERPROFILE%\rigBuilder\modules`

RigBuilder creates the local directory and settings file automatically on first import.

## Testing

Run core tests from this directory:

```bash
pytest test_core.py -v
pytest test_core.py --cov=core --cov-report=term-missing
```

## Repository layout

- `core.py` - module/attribute model, XML IO, runtime API registry.
- `ui.py` - main RigBuilder window and authoring workflow.
- `functionBrowser.py` - inspect Python files and execute functions via generated controls.
- `editor.py` - embedded code editor, highlighting, search helpers.
- `widgets/` - widget templates and UI helpers for attribute editing.
- `run.py` - standalone launcher.
