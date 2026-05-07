# main entry point for running the application

import os
import sys

directory = os.path.dirname(__file__)
sys.path.append(os.path.dirname(directory))

from rigBuilder.qt import QApplication, QColor, QPalette, QSharedMemory, QMessageBox

def updatePalette(app: QApplication):
    # Set global link color
    palette = app.palette()
    palette.setColor(QPalette.Link, QColor("#55aaee"))
    palette.setColor(QPalette.LinkVisited, QColor("#55aaee"))
    app.setPalette(palette)

def applyStylesheet(widget):
    """Load and apply stylesheet."""
    stylesheetPath = os.path.join(directory, "stylesheet.css")
    with open(stylesheetPath, "r", encoding="utf-8") as f:
        content = f.read()

    rootPath = os.path.abspath(directory).replace("\\", "/")
    content = content.replace("{ROOT}", rootPath)
    widget.setStyleSheet(content)

if __name__ == "__main__":
    app = QApplication([])

    applyStylesheet(app)
    updatePalette(app)
    
    # Prevent multiple instances
    sharedMemory = QSharedMemory("RigBuilder_Unique_Lock")
    if not sharedMemory.create(1):
        QMessageBox.warning(None, "Rig Builder", "RigBuilder is already running.\n\nOnly one instance is allowed at a time.")
        sys.exit(0)

    from rigBuilder.logger import setupStreamRedirection, setupExcepthook
    setupStreamRedirection()
    setupExcepthook()

    from rigBuilder.ui import mainWindow
    mainWindow.show()

    app.exec()
