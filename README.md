<div align="center">
   
   [![GitHub release](https://img.shields.io/github/v/release/azagoruyko/rigBuilder?color=green&logo=github)](https://github.com/azagoruyko/rigBuilder/releases)
   ![Commits since latest release](https://img.shields.io/github/commits-since/azagoruyko/rigBuilder/latest)
   
   <img width="64" height="64" alt="icon" src="https://github.com/user-attachments/assets/2430f885-223b-4c67-83a8-101f69c24d14" />
   
</div>

**Rig Builder** is a powerful, standalone environment for managing and executing complex Python script hierarchies across any host application (Maya, Blender, Unreal Engine, etc.).

While initially developed for rigging, it has evolved into a versatile tool for building pipeline utilities, automation scripts, and custom DCC tools through a visual, module-based workflow. By assembling reusable building blocks, you can create anything from complex rigs to production-ready scene management tools.

<img width="1359" height="939" alt="Screenshot 2026-07-26 203558" src="https://github.com/user-attachments/assets/64c810a8-c812-46c7-8600-ea93d7e831f9" />

## ⚙️ Core Concepts

At its heart, Rig Builder operates on a **graph-based hierarchy of modules**:

- **📦 Modules**: The primary building blocks. Modules can represent anything from a rigging step (e.g., Spine, Limb) to a general utility (e.g., Batch Exporter, Scene Cleanup).
- **🎛️ Attributes**: Parameters that define module behavior. Attributes can hold any JSON-compatible data.
- **🔗 Connections**: Attributes can be "wired" together using relative path (e.g., `/parent/input`).
- **🧠 Expressions**: They alter attribute values at time of value resolution.
- **🖥️ Host Connectivity**: Rig Builder connects to host applications and executes modules inside, bringing the result back in real-time.
- **🚀 Execution**: When triggered, modules execute top-to-bottom **inside the host application**, driving the DCC/Engine via its native API.
- **💼 Workspaces**: Isolated environments that encapsulate your script hierarchies, Git-backed history, and dedicated tool settings.

## ✨ Key Features

- **⌨️ Modern Scripting IDE** — Embedded Python IDE with syntax highlighting and code execution across DCCs.
- **💼 Workspace Management** — Organize your work into isolated projects. Seamlessly switch between different toolsets, rigs, or automated pipelines while maintaining focused module hierarchies and persistent environment settings.
- **🤖 Agentic AI Chat** — Enhanced Ollama integration with tool-calling capabilities. The AI can now perform semantic searches across modules, write code, add attributes, and much more!
- **🔍 Semantic Module Indexing** — Intelligent search that understands the functionality of your scripts. Uses vector embeddings to find the right modules using natural language queries.
- **🛰️ Automatic Host Detection** — Zero-configuration connectivity. Rig Builder automatically detects and connects to running instances of Maya, Blender, and Unreal Engine.
- **📟 Integrated REPL** — A powerful, host-aware Python REPL for immediate feedback and interactive debugging within your current workspace.
- **📜 Git-Backed Module History** — Built-in version control for every module change. Track every save, view granular diffs, and restore previous versions in seconds.
- **🔄 Native Auto-Sync** — Real-time synchronization between the application and your files on disk, ensuring your UI always reflects the latest changes.
- **📝 Responsive Markdown Docs** — Author and view module documentation in native Markdown for a modern documentation experience.
- **🔌 Model Context Protocol (MCP)** — Built-in MCP server exposing workspace modules, allowing external AI agents (or vscode-like editors) to query, inspect, and modify your modules.

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

Rig Builder features **Automatic Host Detection**. When you launch a supported host (Maya, Blender, Unreal Engine), it will automatically appear in the Host Manager.

To execute scripts inside a host, you need **`zmq`** (or `pyzmq`) installed in that host's Python environment.

💡 `zmq` will be automatically installed on the first connection if it's missing (using a non-intrusive local installation).

### 5. Usage

To get started with building your own modules, take a look at the [example.rb](modules/example.rb) module provided in the `modules` directory. This serves as a primary reference for module structure and usage patterns.

## 🖥️ Host Requirements

To execute Rig Builder modules inside a host application (like Maya, Blender, or Unreal Engine), the host must meet the following requirements:

- **Python**: Version 3.6+ available within the host environment.
- **zmq** (or `pyzmq`): Required for high-performance communication between Rig Builder and the host.
  - *Note: Rig Builder will attempt to automatically install `zmq` into the host environment on first connection if it is missing.*

## 🧪 Testing

Run tests using `pytest` from the project root:

```bash
pytest test_core.py -v
```
