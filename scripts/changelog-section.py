"""Print one version's section of CHANGELOG.md (used for release notes).

Usage: python3 scripts/changelog-section.py 0.6.0
"""

import re
import sys
from pathlib import Path

version = sys.argv[1]
text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text()
match = re.search(rf"^## \[?{re.escape(version)}\]?.*?\n(.*?)(?=^## |\Z)", text, re.S | re.M)
if not match or not match.group(1).strip():
    sys.exit(f"CHANGELOG.md has no section for {version}")
print(match.group(1).strip())
