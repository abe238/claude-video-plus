"""v1.5.3 A2: every external workflow action is pinned to an immutable SHA
(credit vcolombo). A floating tag (`@v4`) re-resolves on the publisher's side:
a compromised action repo can move it silently — with release.yml holding a
token that can write releases. Full 40-hex commit SHAs cannot move.
"""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.MULTILINE)
PINNED_RE = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")


def test_every_external_action_is_sha_pinned():
    workflow_files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert workflow_files, "no workflow files found"
    unpinned = []
    seen = 0
    for path in workflow_files:
        for match in USES_RE.finditer(path.read_text(encoding="utf-8")):
            ref = match.group(1)
            if ref.startswith("./"):
                continue  # local composite actions ship with the repo
            seen += 1
            if not PINNED_RE.match(ref):
                unpinned.append(f"{path.name}: {ref}")
    # Positive control: the suite must actually be inspecting actions.
    assert seen >= 5, f"expected at least 5 external uses:, saw {seen}"
    assert unpinned == [], f"unpinned actions: {unpinned}"


def test_pins_carry_a_version_comment():
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "uses:" in line and "@" in line and "./" not in line:
                assert re.search(r"#\s*v\d", line), (
                    f"{path.name}: pinned action missing version comment: {line.strip()}"
                )


def test_dependabot_updates_action_pins():
    # No YAML parser in the stdlib toolchain — assert the exact structural
    # lines, not a substring that any comment would satisfy.
    config = (WORKFLOWS.parents[0] / "dependabot.yml").read_text(encoding="utf-8")
    lines = [line.strip() for line in config.splitlines() if line.strip()]
    assert '- package-ecosystem: "github-actions"' in lines
    assert 'directory: "/"' in lines
    assert 'interval: "weekly"' in lines
