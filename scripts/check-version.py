"""Check that the mod, the bridge package and (optionally) a release tag agree on the version.

Usage: python3 scripts/check-version.py [vX.Y.Z]    -> prints the version, exits 1 on mismatch
"""

import json
import re
import sys
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parent.parent
versions = {
    "mod/opcua-io/info.json": json.loads((root / "mod/opcua-io/info.json").read_text())["version"],
    "bridge/pyproject.toml": tomllib.loads((root / "bridge/pyproject.toml").read_text())["project"]["version"],
    "bridge/factorio_opcua/__init__.py": re.search(
        r'__version__ = "([^"]+)"', (root / "bridge/factorio_opcua/__init__.py").read_text()).group(1),
}
if len(sys.argv) > 1:
    versions["tag " + sys.argv[1]] = sys.argv[1].removeprefix("v")

if len(set(versions.values())) != 1:
    for where, version in versions.items():
        print(f"{version:>10}  {where}", file=sys.stderr)
    sys.exit("version mismatch")
if not re.fullmatch(r"\d+\.\d+\.\d+", next(iter(versions.values()))):
    sys.exit("versions must be X.Y.Z (Factorio requires three numbers)")
print(next(iter(versions.values())))
