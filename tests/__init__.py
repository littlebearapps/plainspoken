"""Test package. Puts lib/ on sys.path so `import plainspoken` works under `unittest discover -s tests -t .`."""
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
