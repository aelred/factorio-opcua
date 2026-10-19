"""changelog.txt must follow Factorio's format, or the game and the mod portal reject or garble it."""

import json
import re
import subprocess
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parents[1] / "opcua-io"
ROOT = MOD.parents[1]

LINE = re.compile(
    r"-{99}"                    # separator before each version
    r"|Version: \d+\.\d+\.\d+"
    r"|Date: \S.*"
    r"|  [A-Z][\w ]*:"         # category
    r"|    - \S.*"              # entry
    r"|      \S.*"              # entry continued
)


def test_every_line_has_a_valid_shape():
    lines = (MOD / "changelog.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "-" * 99 and lines[1].startswith("Version: ")
    bad = [(n, line) for n, line in enumerate(lines, 1) if not LINE.fullmatch(line)]
    assert not bad, f"lines not in Factorio's changelog format: {bad}"


def test_current_version_has_a_section_and_release_notes():
    version = json.loads((MOD / "info.json").read_text())["version"]
    notes = subprocess.run([sys.executable, ROOT / "scripts/changelog-section.py", version],
                           capture_output=True, text=True, check=True).stdout
    assert notes.startswith("**") and "\n- " in notes  # categories in bold, entries as a list
    assert "    " not in notes  # continuation lines joined onto their entry
