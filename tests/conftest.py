import sys
from pathlib import Path

# Make the project root importable so test files can `import billing` etc.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
