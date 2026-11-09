import os
import sys

# Allow `import app...` when running `pytest tests/unit` from the project root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
