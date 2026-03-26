# 🏗️ RigBuilder

[![GitHub release](https://img.shields.io/github/v/release/azagoruyko/rigBuilder?color=green&logo=github)](https://github.com/azagoruyko/rigBuilder/releases)
[![Docs](https://img.shields.io/badge/docs-wiki-blue?logo=github)](https://github.com/azagoruyko/rigBuilder/wiki/Documentation)

**RigBuilder** is a standalone application for managing scripts and complex hierarchies of scripts with the connections and expressions which can be executed in any host application (Maya, Blender, Unreal Engine, etc.).

It provides a visual, module-based workflow for building character rigs and pipeline tools by assembling reusable building blocks.

<img width="1373" height="1008" alt="Screenshot 2026-03-25 174827" src="https://github.com/user-attachments/assets/5e936582-9e2c-4c58-a5cb-7fcadd00b12c" />

---

## ⚙️ Core Concepts

At its heart, RigBuilder operates on a **graph-based hierarchy of modules**:

- **📦 Modules**: The primary building blocks. Each module represents a specific step (e.g., Spine, Limb, Rig Utilities).
- **🎛️ Attributes**: Parameters that define module behavior. Attributes can hold any JSON-compatible data and dynamic **Python expressions**.
- **🔗 Connections**: Attributes can be "wired" together using absolute or relative paths (e.g., `/parent/input`).
- **🧠 Expressions**: They alter attribute values at time of value resolution.
- **🖥️ Host Connectivity**: RigBuilder connects to host applications and executes modules inside bringing the result back.
- **🚀 Execution**: When triggered, modules execute top-to-bottom **inside the host application**, driving the DCC/Engine via its API.

---

## ✨ Key Features

- **📦 Module-based assembly** — Define rig steps as XML modules and arrange them in a hierarchy to run the full pipeline from one place.
- **📜 Module history** — Built-in, git-backed history browser for all module changes. Track every save, view diffs, and restore versions instantly.
- **🖥️ DCC Agnostic** — RigBuilder communicates with **Maya**, **Blender**, **Unreal Engine**, or any other Python-capable host.
- **🔍 Function browser** — Discover and run Python functions from a folder without leaving the UI.
- **🤖 AI-Assisted Editing** — Use the **"Edit in VS Code"** button to export modules for external editing inside your favorite VS Code based editor, optimized for AI assistance.

---

## 🚀 Quick Start

### 1. Installation
Clone the repository and run the installation script which will set up a virtual environment and install dependencies:
```bash
git clone https://github.com/azagoruyko/rigBuilder.git
cd rigBuilder
install.bat
```

### 2. Launch
Run RigBuilder using the launch script:
```bash
run.bat
```

### 3. Host Setup (Connectivity)
To execute modules inside a host, you must install **`zmq`** (or `pyzmq`) in that host's Python environment. Replace `<path>` with your specific installation directory.

#### 🎨 Maya
- **Python**: `C:\Program Files\Autodesk\Maya<version>\bin\mayapy.exe`
- **Install**: `mayapy.exe -m pip install zmq`

#### 🧱 Blender
- **Python**: `C:\Program Files\Blender Foundation\Blender<version>\python\bin\python.exe`
- **Install**: `.\python.exe -m pip install zmq`
- **In case of troubles**: try `.\python.exe -m pip install --upgrade --target="BLENDER-PATH\python\lib\site-packages" pyzmq`

#### 🎮 Unreal Engine (5.6+)
1. Enable the **"Python Editor Script Plugin"** in Settings.
2. **Python**: `C:\Program Files\Epic Games\UE_<version>\Engine\Binaries\ThirdParty\Python3\Win64\python.exe`
3. **Install**: `.\python.exe -m pip install zmq`
4. 💡 **Tip**: Install `unreal-stub` for autocompletion in your IDE.

---

## 🛠️ Dependencies

- **Python** ≥ 3.9
- **PySide6** ≥ 6.0.0 (Standalone UI)
- **pyzmq** ≥ 24.0.0 (Host connectivity)
- **markdown** ≥ 3.0.0 (Module documentation)
- **pytest** ≥ 7.0.0 (Testing)

---

## 🧪 Testing

Run tests using `pytest` from the project root:

```bash
pytest test_core.py -v
```
