import os
import sys

# Make the repo root importable so `settlemint` and `scripts` resolve when the
# suite is run with PYTHONPATH=<repo>.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
