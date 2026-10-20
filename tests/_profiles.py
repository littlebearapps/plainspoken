"""Three fixture profiles for the tests: a product voice, a consulting voice and a narrative voice."""
from pathlib import Path

from plainspoken import profile as _profile

_FIX = Path(__file__).parent / "fixtures" / "profiles"
PRODUCT = _profile.load(_FIX / "product_like.toml")
CONSULTING = _profile.load(_FIX / "consulting_like.toml")
NARRATIVE = _profile.load(_FIX / "narrative_like.toml")
