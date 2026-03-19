# 🏗️ RigBuilder

[![GitHub release](https://img.shields.io/github/v/release/azagoruyko/rigBuilder?color=green&logo=github)](https://github.com/azagoruyko/rigBuilder/releases)
[![Documentation](https://img.shields.io/badge/docs-blue?logo=read-the-docs)](https://github.com/azagoruyko/rigBuilder/wiki/Documentation)

**RigBuilder** is a visual, module-based tool for building character and creature rigs—and related pipeline tools—in DCC applications.

It provides a consistent, maintainable way to assemble rigs from building blocks (spine, limbs, face, fingers, etc.) and to share or version those setups as XML.

![RigBuilder UI](https://github.com/user-attachments/assets/922a8f6e-c48e-41e2-bcfb-ab4596f90ea0)

---

## ⚙️ How it works

The core of the system is a **hierarchy of modules**, each with **attributes** (parameters, connections, widget types) and **run code** (module-level Python and per-attribute expressions).

The graph defines the execution order. When you run the pipeline, modules execute in that order and drive the DCC. Everything else builds on this foundation.

---

## ✨ Key Features

   **📦 Module-based assembly** — Define rig steps as XML modules and arrange them in a hierarchy to run the full pipeline from one place.

   **🔗 Visual wiring** — Connect outputs of one module to inputs of another using path-style references (`/path/to/attr`).

   **📜 Module history** — Built-in, git-backed history browser for all module changes. It allows you to track every save, view precise diffs between versions, and instantly restore or re-add previous module configurations to your tree. Requires no manual setup beyond having Git installed.

   **🖥️ DCC Agnostic** — Use it inside **Maya**, **Blender**, or any other Python-capable DCC; each host registers its operations via `APIRegistry`.

   **🔍 Function browser** — Discover and run Python functions from a folder without leaving the UI.

   **💾 Workspace persistence** — Automatically save and restore your module tree and layout before each run and on quit.

   **📂 Local and server modules** — Use local modules for testing and server paths (via module selector) for shared team libraries.

   **🤖 AI-Assisted Editing** — Use the **"Edit in VS Code"** context menu option to export modules for external editing. This workflow is optimized for AI assistance, providing a dedicated `AI_context.md` for prompts and a sidecar `_predef.py` file for autocomplete and type hinting.

---

## 🚀 Quick Start

### In Maya
```python
import rigBuilder.ui
rigBuilder.ui.mainWindow.show()
```

### Standalone (no DCC)
```bash
python run.py
```
> DCC is auto-detected (e.g. Maya when `maya.cmds` is available); otherwise the UI runs in standalone mode for testing and development.

> **Note:** [Git](https://git-scm.com/downloads) is required for the Module History feature.

---

## 🛠️ Dependencies

- **PySide6** ≥ 6.0.0 (or PySide2 in Maya)
- **markdown** ≥ 3.0.0 (for module documentation rendering)
- **pytest** ≥ 7.0.0 (for testing)

Check [requirements.txt](requirements.txt) for more details.

---

## 🧪 Testing

Run tests using `pytest` from the project root:

```bash
pytest test_core.py -v
pytest test_core.py --cov=core --cov-report=term-missing
```

---

📖 **Full documentation is available in the [Wiki](https://github.com/azagoruyko/rigBuilder/wiki/Documentation).**
