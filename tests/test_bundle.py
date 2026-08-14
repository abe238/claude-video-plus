import hashlib
import zipfile
from pathlib import Path

from tools.build_skill_bundle import MAX_BYTES, RUNTIME_SCRIPTS, build


ROOT = Path(__file__).resolve().parents[1]


def test_bundle_is_deterministic_lean_and_self_contained(tmp_path):
    first = tmp_path / "first.skill"
    second = tmp_path / "second.skill"
    one = build(ROOT / "skills/watch", first)
    two = build(ROOT / "skills/watch", second)
    assert first.read_bytes() == second.read_bytes()
    assert one["sha256"] == two["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert one["bytes"] < MAX_BYTES
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names.count("watch/SKILL.md") == 1
        assert all(
            name == "watch/SKILL.md"
            or (name.startswith("watch/scripts/") and name.endswith(".py"))
            # v1.4.0: SKILL.md defers cold sections to references/*.md and Reads
            # them on demand, so they are runtime files, not docs.
            or (name.startswith("watch/references/") and name.endswith(".md"))
            for name in names
        )
        assert any(name.startswith("watch/references/") for name in names), \
            "references/ missing from the bundle — installs would hit dead pointers"
        assert "watch/scripts/build-skill.sh" not in names
        assert "watch/.skillignore" not in names
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)


def test_bundle_inventory_matches_runtime_python_sources(tmp_path):
    receipt = build(ROOT / "skills/watch", tmp_path / "watch.skill")
    expected = {"watch/SKILL.md"}
    expected.update(f"watch/scripts/{path.name}" for path in (ROOT / "skills/watch/scripts").glob("*.py"))
    expected.update(f"watch/references/{path.name}" for path in (ROOT / "skills/watch/references").glob("*.md"))
    assert set(receipt["files"]) == expected


def test_bundle_rejects_unexpected_python_and_oversized_output(tmp_path):
    skill = tmp_path / "watch"
    scripts = skill / "scripts"
    scripts.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: watch\ndescription: x\n---\n")
    references = skill / "references"
    references.mkdir()
    (references / "flags.md").write_text("# flags\n")
    for name in RUNTIME_SCRIPTS:
        (scripts / name).write_text("# runtime\n")
    (scripts / "build_helper.py").write_text("# dev only\n")
    with __import__("pytest").raises(ValueError, match="unexpected"):
        build(skill, tmp_path / "unexpected.skill")
    (scripts / "build_helper.py").unlink()
    (scripts / RUNTIME_SCRIPTS[0]).write_bytes(__import__("os").urandom(MAX_BYTES * 2))
    output = tmp_path / "oversized.skill"
    with __import__("pytest").raises(ValueError, match="limit"):
        build(skill, output)
    assert not output.exists()
