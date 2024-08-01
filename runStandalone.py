import sys
import os

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *

app = QApplication([])

os.environ["RIG_BUILDER_DCC"] = "standalone"
import rigBuilder

with open(rigBuilder.RigBuilderPath+"/stylesheet.css") as r:
	app.setStyleSheet(r.read())

rigBuilder.mainWindow.show()
app.exec_()
