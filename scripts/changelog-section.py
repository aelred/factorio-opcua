"""Print one version's section of mod/opcua-io/changelog.txt as Markdown (used for release notes).

The changelog is in Factorio's format, which the game and the mod portal show:
a line of 99 dashes, "Version: X.Y.Z", an optional "Date: ...", then
categories ("  Name:") with entries ("    - text", continued on "      text").

Usage: python3 scripts/changelog-section.py 0.6.0
"""

import sys
from pathlib import Path

version = sys.argv[1]
text = (Path(__file__).resolve().parent.parent / "mod/opcua-io/changelog.txt").read_text(encoding="utf-8")
sections = {}
for block in text.split("-" * 99 + "\n"):
    lines = block.splitlines()
    if lines and lines[0].startswith("Version: "):
        sections[lines[0].removeprefix("Version: ").strip()] = lines[1:]
if not sections.get(version):
    sys.exit(f"changelog.txt has no section for {version}")

out = []
for line in sections[version]:
    if line.startswith("Date: "):
        continue
    if line.startswith("    - "):
        out.append("- " + line[6:])
    elif line.startswith("      "):
        out[-1] += " " + line.strip()
    else:
        out.append(("\n" if out else "") + f"**{line.strip()}**")
print("\n".join(out))
