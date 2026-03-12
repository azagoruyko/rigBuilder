import os
import sys

directory = os.path.dirname(__file__)
sys.path.append(os.path.dirname(directory))
from rigBuilder.qt import QApplication, execFunc

# Set DCC mode before importing rigBuilder
os.environ["RIG_BUILDER_DCC"] = "standalone"

if __name__ == "__main__":
    app = QApplication([])

    import rigBuilder.ui
    rigBuilder.ui.mainWindow.show()

    execFunc(app)
