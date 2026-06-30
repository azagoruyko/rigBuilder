# main entry point for running the application

import os
import sys
from PySide6.QtCore import QSharedMemory

directory = os.path.dirname(__file__)
sys.path.append(os.path.dirname(directory))

if __name__ == "__main__":
    
    # Prevent multiple instances
    sharedMemory = QSharedMemory("RigBuilder_Unique_Lock")
    if not sharedMemory.create(1):
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication([])
        QMessageBox.warning(None, "Rig Builder", "RigBuilder is already running.\n\nOnly one instance is allowed at a time.")
        sys.exit(0)

    from rigBuilder.ui import app, mainWindow
    from rigBuilder.core.connectionManager import connectionManager
    from rigBuilder.host.servers.standalone import StandaloneServer
    
    standaloneServer = StandaloneServer(connectionManager.discoveryPort)
    standaloneServer.start()

    from rigBuilder.mcp.zmq_server import ZmqServer
    zmqServer = ZmqServer(parent=app)
    zmqServer.setMainWindow(mainWindow)

    mainWindow.show()
    sys.exit(app.exec())
