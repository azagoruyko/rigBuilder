# main entry point for running the application

import os
import sys
from functools import partial

directory = os.path.dirname(__file__)
sys.path.append(os.path.dirname(directory))

from rigBuilder.qt import QApplication

if __name__ == "__main__":
    app = QApplication([])

    from rigBuilder.workspace import loadWorkspace, saveWorkspace
    from rigBuilder.ui import mainWindow, saveSettings, cleanupVscode
    from rigBuilder.ui.utils import applyStylesheet

    applyStylesheet(app)

    loadWorkspace(mainWindow)
    mainWindow.show()

    def aboutToQuit():
        """Save workspace and settings (on quit)."""
        saveWorkspace(mainWindow)
        saveSettings()

    mainWindow.aboutToRunModule.connect(partial(saveWorkspace, mainWindow))
    QApplication.instance().aboutToQuit.connect(aboutToQuit)
    
    cleanupVscode()

    app.exec()
