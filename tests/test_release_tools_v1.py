import json
from pathlib import Path

import pytest

from lifecycle import _safe_root, inspect
from tools.grader_validation import agreement
from tools.release_audit import versions


def test_grader_requires_dual_humans_and_meets_agreement_gate():
    rows = [{"case_id": str(index), "human_a": "candidate", "human_b": "candidate", "grader": "candidate"}
            for index in range(20)]
    result = agreement(rows)
    assert result["validated"] and result["accuracy"] == 1
    with pytest.raises(ValueError, match="20"):
        agreement(rows[:19])


def test_release_versions_are_coherent():
    result = versions()
    assert result["coherent"]
    assert set(result.values()) >= {"1.0.0", True}


def test_lifecycle_refuses_unknown_cleanup_root(tmp_path):
    with pytest.raises(ValueError, match="refusing"):
        _safe_root(tmp_path)
    result = inspect()
    assert result["schema_version"] == 1
    assert {"codex", "claude", "agents", "cursor"} <= set(result["installs"])
