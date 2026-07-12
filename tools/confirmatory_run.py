#!/usr/bin/env python3
"""Authorize and execute exactly one frozen confirmatory evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--access-log", type=Path, required=True)
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--candidate-config-hash", required=True)
    parser.add_argument("--custodian-authorization", required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("confirmatory output already exists; cohort cannot be rerun")
    if len(args.custodian_authorization.strip()) < 16:
        raise SystemExit("custodian authorization is missing or too short")
    validation = subprocess.run(
        ["python3", "tools/corpus_registry.py", str(args.registry), "--access-log", str(args.access_log)],
        text=True, capture_output=True,
    )
    if validation.returncode:
        raise SystemExit(validation.stderr or validation.stdout)
    frozen = json.loads(args.registry.read_text(encoding="utf-8")).get("frozen", {})
    if frozen.get("candidate_commit") not in {None, args.candidate_commit}:
        raise SystemExit("candidate commit differs from seal")
    if frozen.get("candidate_config_hash") not in {None, args.candidate_config_hash}:
        raise SystemExit("candidate config differs from seal")
    receipt = {
        "schema_version": 1,
        "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        "registry_sha256": sha256(args.registry),
        "access_log_sha256": sha256(args.access_log),
        "candidate_commit": args.candidate_commit,
        "candidate_config_hash": args.candidate_config_hash,
        "authorization_sha256": hashlib.sha256(args.custodian_authorization.encode()).hexdigest(),
        "evaluation_dir": str(args.evaluation_dir),
        "status": "authorized_once",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
