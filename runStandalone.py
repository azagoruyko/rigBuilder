import sys
import os

# Set DCC mode before importing rigBuilder
os.environ["RIG_BUILDER_DCC"] = "standalone"

# Import PySide6 directly
from PySide6.QtCore import *
from PySide6.QtGui import *  
from PySide6.QtWidgets import *

if __name__ == "__main__":
    app = QApplication([])
    
    # Add parent directory to Python path so rigBuilder can be imported as package
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    
    # Import rigBuilder after Qt is initialized
    import rigBuilder
    from rigBuilder.core import RigBuilderPath
    
    with open(os.path.join(RigBuilderPath, "stylesheet.css"), "r") as f:
        app.setStyleSheet(f.read())
    
    rigBuilder.mainWindow.show()
    app.exec()
