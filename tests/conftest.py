import sys
import os

# Get the path to the directory containing 'tests' (the root 'rigBuilder' repo path)
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Get the parent of 'rigBuilder' so that 'import rigBuilder' works
parent_dir = os.path.dirname(root_dir)

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
