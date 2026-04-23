# Rig Builder

[![GitHub release](https://img.shields.io/github/v/release/azagoruyko/rigBuilder?color=green&logo=github)](https://github.com/azagoruyko/rigBuilder/releases)
![Commits since latest release](https://img.shields.io/github/commits-since/azagoruyko/rigBuilder/latest)

**Rig Builder** is a powerful, standalone environment for managing and executing complex Python script hierarchies across any host application (Maya, Blender, Unreal Engine, etc.).

While initially developed for rigging, it has evolved into a versatile tool for building pipeline utilities, automation scripts, and custom DCC tools through a visual, module-based workflow. By assembling reusable building blocks, you can create anything from complex rigs to production-ready scene management tools.

<img width="1297" height="991" alt="Screenshot 2026-04-06 165901" src="https://github.com/user-attachments/assets/04cb6619-4d76-4a9f-90d8-de4905e53c79" />

---

## ⚙️ Core Concepts

At its heart, Rig Builder operates on a **graph-based hierarchy of modules**:

- **📦 Modules**: The primary building blocks. Modules can represent anything from a rigging step (e.g., Spine, Limb) to a general utility (e.g., Batch Exporter, Scene Cleanup).
- **🎛️ Attributes**: Parameters that define module behavior. Attributes can hold any JSON-compatible data and dynamic **Python expressions**.
- **🔗 Connections**: Attributes can be "wired" together using absolute or relative paths (e.g., `/parent/input`).
- **🧠 Expressions**: They alter attribute values at time of value resolution.
- **🖥️ Host Connectivity**: Rig Builder connects to host applications and executes modules inside, bringing the result back in real-time.
- **🚀 Execution**: When triggered, modules execute top-to-bottom **inside the host application**, driving the DCC/Engine via its native API.
- **💼 Workspaces**: Isolated environments that encapsulate your script hierarchies, Git-backed history, and dedicated tool settings.

---

## ✨ Key Features

- **⚡ Modern Scripting Experience** — A high-performance Python editor tailored for technical artists.
- **💼 Workspace Management** — Organize your work into isolated projects. Seamlessly switch between different toolsets, rigs, or automated pipelines while maintaining focused module hierarchies and persistent environment settings.
- **📜 Git-Backed Module History** — Built-in version control for every module change. Track every save, view granular diffs, and restore previous versions in seconds.
- **🔄 Native Auto-Sync** — Real-time synchronization between the application and your files on disk, ensuring your UI always reflects the latest changes.
- **🖥️ DCC Agnostic** — Seamlessly connects to **Maya**, **Blender**, **Unreal Engine**, or any Python-capable host via a high-performance ZMQ bridge.
- **🤖 Local AI Assistance** — Integrated **Ollama** support for AI-assisted script development, documentation generation, and **semantic module search**.
- **🔍 Semantic Module Indexing** — Find modules by their functionality, not just names. Uses vector embeddings to understand the context of your scripts and documentation.
- **📝 Responsive Markdown Docs** — Author and view module documentation in native Markdown for a modern, clean documentation experience.

---

## 🚀 Quick Start

### 1. Installation

Clone the repository and run the installation script which will set up a virtual environment and install dependencies:

```bash
git clone https://github.com/azagoruyko/rigBuilder.git
cd rigBuilder
install.bat
```

### 2. Ollama AI Setup (Optional)

To enable Local AI Assistance and Semantic Search, install Ollama and pull the required models:

1. **Download**: Install from [ollama.com](https://ollama.com/).
2. **Setup**: Run the installer.
3. **Pull Models**:
   - For code assistance: `ollama pull your-favorite-model` (e.g., `codellama`, `llama3`).
   - For semantic search (REQUIRED for indexing): `ollama pull nomic-embed-text`.

4. **Login (Optional)**: If using cloud models, open your terminal and run `ollama signin`.

   > **Note on Indexing**: Rig Builder automatically indexes your modules using vector embeddings. This allows you to search for modules using natural language (e.g., "how to build a spine").
   >
   > The default models can be customized via the `settings.json` file in your active workspace:
   > - `ollamaModel`: Model for code generation (defaults to `gpt-oss:20b-cloud`).
   > - `ollamaEmbeddingModel`: Model for semantic search (defaults to `nomic-embed-text`).

### 3. Launch

Run Rig Builder using the launch script:

```bash
run.bat
```

### 4. Host Setup (Connectivity)

To execute scripts inside a host, you need **`zmq`** (or `pyzmq`) installed in that host's Python environment.

💡`zmq` will be automatically installed in case you don't have it on the first host connection (use the snippet provided by the Host Manager).

### 5. Usage

To get started with building your own modules, take a look at the [example.rb](modules/example.rb) module provided in the `modules` directory. This serves as a primary reference for module structure and usage patterns.

---

## 🛠️ Dependencies

- **Python** ≥ 3.9
- **PySide6** ≥ 6.0.0 (Standalone UI)
- **pyzmq** ≥ 24.0.0 (Host connectivity)
- **markdown** ≥ 3.1.0 (Module documentation)
- **ollama** (AI connectivity)
- **pytest** ≥ 7.0.0 (Testing)

---

## 🧪 Testing

Run tests using `pytest` from the project root:

```bash
pytest test_core.py -v
```
