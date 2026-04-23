import os
import sys
import subprocess

def getPythonExe():
    """Finds the actual python.exe path for the current application."""
    exe = sys.executable

    # Unreal Engine logic: sys.executable is the Editor itself
    if "UnrealEditor" in exe:
        # Path: [UE_Path]/Engine/Binaries/ThirdParty/Python3/Win64/python.exe
        return os.path.join(os.path.dirname(exe), "../../Binaries/ThirdParty/Python3/Win64/python.exe")

    # Maya/Blender/Other logic: sys.executable is usually the bundled python
    # Note: Maya uses 'mayapy', Blender uses 'python.exe' inside its folder
    return exe

def ensure_zmq():
    try:
        import zmq
        return
    except ImportError:
        pass
                
    pythonExe = getPythonExe()
    print(f"zmq not installed, installing with: {pythonExe}")
    subprocess.check_call([pythonExe, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([pythonExe, "-m", "pip", "install", "pyzmq"])
    import zmq
    print("zmq installed successfully!!!")
