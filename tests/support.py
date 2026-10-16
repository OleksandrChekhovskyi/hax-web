"""Shared test setup. Import this before hax_web: it puts src/ on the path."""

from __future__ import annotations

import pathlib
import sys
from typing import Final

ROOT: Final = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
