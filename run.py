# main entry point for running the application

import os
import sys

directory = os.path.dirname(__file__)
sys.path.append(os.path.dirname(directory))

from rigBuilder.ui import QSharedMemory, QMessageBox

if __name__ == "__main__":
    # Prevent multiple instances
    sharedMemory = QSharedMemory("RigBuilder_Unique_Lock")
    if not sharedMemory.create(1):
        QMessageBox.warning(None, "Rig Builder", "RigBuilder is already running.\n\nOnly one instance is allowed at a time.")
        sys.exit(0)

    from rigBuilder.ui import app, mainWindow

    mainWindow.show()
    sys.exit(app.exec())
