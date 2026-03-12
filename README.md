# RigBuilder

<div>
<img src="https://img.shields.io/github/v/release/azagoruyko/rigBuilder?logoColor=green&color=green"/>
<a href="https://github.com/azagoruyko/rigBuilder/wiki/Documentation">
  <img src="https://img.shields.io/badge/docs-here-blue?label=docs"/>
</a>
</div>

**RigBuilder** is a visual, module-based tool for building character and creature rigs—and related pipeline tools—in DCC applications.

It is **not bound to any single host**: you can use it with **Maya**, **Blender**, or any other DCC that supports Python. Instead of wiring scripts by hand, you compose reusable modules in a graph, set parameters and connections in the UI, and run the pipeline with progress feedback and logging.

It is aimed at riggers and TDs who want a consistent, maintainable way to assemble rigs from building blocks (spine, limbs, face, fingers, etc.) and to share or version those setups as XML.

<img width="1294" height="916" alt="image" src="https://github.com/user-attachments/assets/f47a27a8-57c5-4f32-b118-9ef77d513796" />

Full documentation is [here](https://github.com/azagoruyko/rigBuilder/wiki/Documentation).

---

## ✨ What it does

**Core of the system:** a **hierarchy of modules**, each with **attributes** (parameters, connections, widget types) and **run code** (module-level Python and per-attribute expressions). The graph defines execution order; when you run the pipeline, modules execute in that order and drive the DCC. Everything else builds on this.

- **📦 Module-based rig assembly** — Define rig steps as XML modules (e.g. spine, legs, face, fingers), arrange them in a hierarchy, and run the full pipeline from one place.
- **🔗 Visual wiring** — Connect outputs of one module to inputs of another using path-style references (`/path/to/attr`). No need to remember script APIs; the graph shows the flow.
- **🔍 Function browser** — Discover and run Python helpers from a folder without leaving the UI.
- **🖥️ Any DCC or standalone** — Use it inside Maya, Blender, or any other Python-capable DCC; each host registers its operations via APIRegistry so modules stay host-agnostic. Or run the same UI in a standalone Qt process for testing and tool development.
- **💾 Workspace persistence** — Your module tree and layout are saved automatically before each run and on quit, and restored on startup.
- **📂 Local and server modules** — Treat local modules as a testing layer for refining modules before publishing them to the server; optionally set a server path (via the module selector menu) for shared/team module libraries.

---

## 🚀 Quick start

### In Maya

```python
import rigBuilder.ui
rigBuilder.ui.mainWindow.show()
```

### Standalone 🖥️ (no DCC)

```bash
python run.py
```

`run.py` sets `RIG_BUILDER_DCC=standalone` so the UI runs without a DCC. Inside a host (Maya, Blender, etc.), leave `RIG_BUILDER_DCC` unset or set it to the host name; the active DCC registers its operations into `APIRegistry`, so modules and the UI call DCC operations through that abstraction rather than host-specific APIs.

---

## 📋 Dependencies

From `requirements.txt`:

- **PySide6** ≥ 6.0.0 (default for standalone in this repo)
- **pytest** ≥ 7.0.0, **pytest-cov** ≥ 4.0.0 (for tests)

Notes:

- In Maya, **PySide2** is usually provided by the application.
- Standalone can use either PySide2 or PySide6; `qt.py` tries PySide2 first, then PySide6.
- `requirements.txt` pins PySide6 for convenience; standalone is not limited to it.

---

## 🧪 Testing

From the project root:

```bash
pytest test_core.py -v
pytest test_core.py --cov=core --cov-report=term-missing
```
