"""Judge validation report: TPR/TNR per judge group and model, with the accept bar.

A thin wrapper over `plainspoken eval judges-report`: `python3 scripts/dev/judge_validate.py --run DIR [--min 0.8]`.
Exit codes are the command's: 0 every model meets the bar · 1 one misses it · 2 a missing or unreadable run."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from plainspoken.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["eval", "judges-report", *sys.argv[1:]]))
