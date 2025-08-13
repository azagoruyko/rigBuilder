import os
import sys
from PySide6.QtWidgets import QApplication

directory = os.path.dirname(__file__)

# Set DCC mode before importing rigBuilder
os.environ["RIG_BUILDER_DCC"] = "standalone"

if __name__ == "__main__":
    app = QApplication([])

    # Apply stylesheet
    with open(os.path.join(directory, "stylesheet.css"), "r") as f:
        app.setStyleSheet(f.read())

    sys.path.append(os.path.dirname(directory))

    import rigBuilder.ui
    rigBuilder.ui.mainWindow.show()

    app.exec()
