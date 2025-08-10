# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Architecture

rigBuilder is a flexible and extendable UI maker for Python scripts, designed to work with any DCC that supports Qt/PySide framework. It uses a module-based architecture for creating tools.

### Qt Framework

The project uses **PySide6** for Qt framework support:
- Modern Qt6 framework for newer Maya versions (2025+) and standalone usage
- Maya integration uses shiboken6 for proper widget wrapping

### Core Components

- **Main Entry Point**: `__init__.py` - Contains the main window (`RigBuilderWindow`) and application initialization
- **Core**: `core.py` - Core data structures including `Module`, `Attribute`, and XML handling
- **Widgets**: `widgets.py` - UI template widgets and dialog classes for the interface
- **Editor**: `editor.py` - Code editor with syntax highlighting and completion
- **JSON Widget**: `jsonWidget.py` - Specialized widget for JSON data editing
- **Utils**: `utils.py` - Utility functions and helpers

### Module System

- Modules are stored as XML files in `modules/` directory
- Each module can contain attributes, code, and child modules
- Supports local and server-based module storage
- Modules can be loaded from files or embedded directly

### UI Architecture

The main window consists of:
- **Tree Widget**: Displays module hierarchy (left panel)
- **Attributes Panel**: Shows module attributes and controls (right panel)  
- **Code Editor**: For editing module Python code (bottom panel)
- **Log Widget**: Output and error messages (bottom panel)

## Running the Application

### Standalone Mode
```python
python runStandalone.py
```

### Maya Integration
The application can be used within Autodesk Maya when the `RIG_BUILDER_DCC` environment variable is set to "maya".

### Module Loading
- Press **TAB** in the tree widget to browse and load modules
- Modules can be dragged and dropped from file explorer
- Use **Ctrl+I** to import individual module files

## Key Features

- **Module Browser**: TAB key opens module selector dialog
- **VSCode Integration**: Edit module code in Visual Studio Code with IntelliSense
- **Version Control**: Built-in support for server synchronization
- **Diff Viewer**: Compare modules with saved versions or server versions
- **Template System**: Extensible widget templates for different data types

## Development Notes

- Uses PySide6 for Qt framework
- Requires Python 3.6+ (Python 2 support removed)
- Module data stored in `$USERPROFILE\rigBuilder` on Windows
- Settings stored in `settings.json` with VSCode path configuration
- Custom stylesheet in `stylesheet.css` for UI theming

## File Paths and Storage

- **Module Storage**: `$USERPROFILE\rigBuilder\modules` (local), `{install_path}\modules` (server)
- **Settings**: `$USERPROFILE\rigBuilder\settings.json`
- **VSCode Integration**: `$USERPROFILE\rigBuilder\vscode`

## Common Operations

- **New Module**: Insert key or right-click menu
- **Save Module**: Ctrl+S
- **Duplicate**: Ctrl+D  
- **Update from Server**: Ctrl+U
- **Run Module**: Click "Run!" button
- **Mute/Unmute**: M key
- **Remove**: Delete key