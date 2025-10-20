# RigBuilder

<div>
<img src="https://img.shields.io/github/v/release/azagoruyko/rigBuilder?logoColor=green&color=green"/>
<a href="https://github.com/azagoruyko/rigBuilder/wiki/Documentation">
  <img src="https://img.shields.io/badge/docs-here-blue?label=docs"/>
</a>
</div>

**Visual tool builder for Python scripts**

Create custom interfaces for your Python scripts using drag-and-drop modules. Works standalone or inside any application that supports PySide/Qt.

**PySide2 is not supported since v5.0.0 tag.**


![rb_example](https://github.com/user-attachments/assets/51961be9-ae99-4fae-aa70-1080305c286d)

## What it does

- **Visual interface builder** - Create GUIs for Python scripts without traditional programming
- **Module system** - Organize code into reusable blocks with inputs/outputs  
- **Multiple widget types** - Sliders, file pickers, tables, lists, curves, and more
- **Live code editing** - Write Python directly in modules with syntax highlighting
- **Connections** - Link modules together, values update automatically
- **Runs anywhere** - Standalone app or embedded in Maya, Blender, etc.

## Use cases

- **File processing** - Batch convert, rename, or analyze files
- **Data tools** - CSV processing, chart generation, data analysis  
- **3D workflows** - Custom tools for Maya, Blender, etc.
- **Prototyping** - Quick GUI mockups for Python scripts
- **Automation** - Turn command-line scripts into user-friendly tools


## Installation

```bash
git clone https://github.com/azagoruyko/rigBuilder.git
cd rigBuilder
pip install -r requirements.txt
python run.py
```

**Requirements:** Python 3.7+, PySide6

**DCC Integration:** Import `rigBuilder.ui` module and call `rigBuilder.ui.mainWindow.show()`

## How it works

Modules are saved as XML files containing Python code and widget configurations. You can organize them in hierarchies, connect outputs to inputs, and share them between projects.

## Contributing

Found a bug or have an idea? Open an [issue](../../issues) or submit a pull request.

## License

MIT License - use freely in personal and commercial projects.
