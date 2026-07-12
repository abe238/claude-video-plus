#!/usr/bin/env bash
# build-skill.sh — package the watch skill as a claude.ai-upload-ready .skill file.
# Usage: bash skills/watch/scripts/build-skill.sh   (run from anywhere)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "error: working tree is dirty; commit or stash before building" >&2
  exit 1
fi

python3 tools/build_skill_bundle.py \
  --skill-dir skills/watch \
  --output dist/watch.skill
echo "upload via the claude.ai skill UI"
