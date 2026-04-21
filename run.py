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

if __name__ == "__main__":
    app = QApplication([])
    
    # Prevent multiple instances
    sharedMemory = QSharedMemory("RigBuilder_Unique_Lock")
    if not sharedMemory.create(1):
        QMessageBox.warning(None, "RigBuilder", "RigBuilder is already running.\n\nOnly one instance is allowed at a time.")
        sys.exit(0)

    from rigBuilder.logger import setupStreamRedirection, setupExcepthook
    setupStreamRedirection()
    setupExcepthook()

    from rigBuilder.ui import mainWindow
    from rigBuilder.ui.utils import applyStylesheet

    applyStylesheet(app)
    updatePalette(app)

    mainWindow.show()

    app.exec()
