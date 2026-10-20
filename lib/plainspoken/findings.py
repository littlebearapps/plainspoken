"""Finding — one rule hit at one place in an article."""
from dataclasses import asdict, dataclass

SEVERITIES = ("BLOCK", "WARN", "CANDIDATE", "INFO")


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str  # one of SEVERITIES
    line: int      # 1-based line in the source file (0 = whole article)
    excerpt: str   # the matched text, trimmed to 160 chars
    message: str   # what's wrong + the fix, AusEnglish
    source: str = "lint"

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"bad severity {self.severity!r}")

    def to_dict(self) -> dict:
        return asdict(self)
