import os
import sys
import subprocess
import importlib

def getPythonExe():
    """Finds the actual python.exe path for the current application."""
    exe = sys.executable

    # Unreal Engine logic: sys.executable is the Editor itself
    if "UnrealEditor" in exe:
        ueBin = os.path.dirname(exe)
        for rel in ["../ThirdParty/Python3/Win64/python.exe", "../../Binaries/ThirdParty/Python3/Win64/python.exe"]:
            candidate = os.path.normpath(os.path.join(ueBin, rel))
            if os.path.exists(candidate): 
                return candidate

    # Maya logic
    if "maya.exe" in exe.lower():
        return os.path.join(os.path.dirname(exe), "mayapy.exe")

    # Blender logic: sys.executable is the blender.exe, python is in a versioned subfolder
    if "blender.exe" in exe.lower():
        base = os.path.dirname(exe)
        for d in os.listdir(base):
            pyPath = os.path.join(base, d, "python", "bin", "python.exe")
            if os.path.exists(pyPath): 
                return pyPath

    return exe

def _isZmqAvailable():
    """Checks if zmq is available and functional, attempting to reload if necessary."""
    importlib.invalidate_caches()
    try:
        import zmq
        if not hasattr(zmq, "zmq_version"):
            raise ImportError("zmq module shadowed or empty")
        zmq.zmq_version()
        return True
    except Exception:
        # Purge from sys.modules to allow a clean re-import
        for m in list(sys.modules.keys()):
            if m == "zmq" or m.startswith("zmq."):
                del sys.modules[m]
        return False

def ensure_zmq():
    """Main entry point to ensure pyzmq is available for the host adapter."""
    if _isZmqAvailable():
        return

    # Calculate version-specific vendor dir (e.g. ~/rigBuilder/vendor/py311)
    userDir = os.path.normpath(os.path.join(os.path.expanduser("~"), "rigBuilder"))
    pyVer = f"py{sys.version_info.major}{sys.version_info.minor}"
    vendorDir = os.path.join(userDir, "vendor", pyVer)

    # Add to path and check again
    if vendorDir not in sys.path:
        sys.path.insert(0, vendorDir)

    if _isZmqAvailable():
        return

    # Not found in project or vendor, perform installation
    if not os.path.exists(vendorDir):
        os.makedirs(vendorDir)

    pythonExe = getPythonExe()
    print(f"RigBuilder: zmq not found for {pyVer}, installing to vendor with: {pythonExe}")

    try:
        # Bootstrap pip (critical for Unreal and some Blender setups)
        try:
            subprocess.check_call([pythonExe, "-m", "ensurepip"], 
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        # Install directly to the centralized vendor directory
        subprocess.check_call([pythonExe, "-m", "pip", "install", "--upgrade", "--target", vendorDir, "pyzmq"])

        # Final verification
        if _isZmqAvailable():
            import zmq
            print(f"RigBuilder: zmq {zmq.zmq_version()} installed to {vendorDir} successfully.")
        else:
            print("RigBuilder ERROR: pyzmq installed but could not be loaded.")
            
    except Exception as e:
        print(f"RigBuilder ERROR: Failed to install or load zmq: {e}")
