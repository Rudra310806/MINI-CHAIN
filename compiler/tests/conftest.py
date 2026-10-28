"""Configure imports for the existing top-level compiler modules."""

import sys
from pathlib import Path


COMPILER_DIR = Path(__file__).resolve().parents[1]
if str(COMPILER_DIR) not in sys.path:
    sys.path.insert(0, str(COMPILER_DIR))
