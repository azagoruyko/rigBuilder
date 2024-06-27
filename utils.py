import sys
import re
from contextlib import contextmanager

from PySide2.QtGui import *
from PySide2.QtCore import *
from PySide2.QtWidgets import *

def Callback(f, *args, **kwargs):
   return lambda: f(*args, **kwargs)

def clamp(val, low, high):
    return max(low, min(high, val))

def replaceSpecialChars(text):
    return re.sub("[^a-zA-Z0-9_]", "_", text)

def replacePairs(pairs, text):
    for k, v in pairs:
        text = re.sub(k, v, text)
    return text

@contextmanager
def captureOutput(stream):
    default_stdout = sys.stdout
    default_stderr = sys.stderr

    sys.stdout = stream
    sys.stderr = stream
    yield
    sys.stdout = default_stdout
    sys.stderr = default_stderr

def printErrorStack():
    exc_type, exc_value, exc_traceback = sys.exc_info()

    tbs = []
    tb = exc_traceback
    while tb:
        tbs.append(tb)
        tb = tb.tb_next

    skip = True
    indent = "  "
    for tb in tbs:
        if tb.tb_frame.f_code.co_filename == "<string>":
            skip = False

        if not skip:
            print("{}{}, {}, in line {},".format(indent, tb.tb_frame.f_code.co_filename, tb.tb_frame.f_code.co_name, tb.tb_lineno))
            indent += "  "
    print("Error: {}".format(exc_value))

def centerWindow(window):
    screen = QDesktopWidget().screenGeometry()
    cp = screen.center()
    geom = window.frameGeometry()
    geom.moveCenter(cp)
    window.move(geom.topLeft())

def clearLayout(layout):
     if layout is not None:
         while layout.count():
             item = layout.takeAt(0)
             widget = item.widget()
             if widget is not None:
                 widget.setParent(None)
             else:
                 clearLayout(item.layout())
                 