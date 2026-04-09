# main entry point for running the application

import os
import sys
from functools import partial

directory = os.path.dirname(__file__)
sys.path.append(os.path.dirname(directory))

from rigBuilder.qt import QApplication, QColor, QPalette

def updatePalette(app: QApplication):
    # Set global link color
    palette = app.palette()
    palette.setColor(QPalette.Link, QColor("#55aaee"))
    palette.setColor(QPalette.LinkVisited, QColor("#55aaee"))
    app.setPalette(palette)

if __name__ == "__main__":
    app = QApplication([])

    from rigBuilder.ui import mainWindow, cleanupVscode
    from rigBuilder.settings import settings, appState
    from rigBuilder.ui.utils import applyStylesheet

    applyStylesheet(app)
    updatePalette(app)

    mainWindow.show()

    def aboutToQuit():
        """Save workspace and state (on quit)"""
        mainWindow.workspaceWidget.toWorkspace().save()
        appState.save()

    QApplication.instance().aboutToQuit.connect(aboutToQuit)
    
    cleanupVscode()

    app.exec()
