#!/usr/bin/env bash
# Fail when generated files under PATH differ from what is committed (modified or untracked).
# Usage: scripts/check-clean.sh <path> <hint>
set -euo pipefail

path="$1"
hint="$2"

if git diff --quiet -- "$path" && [[ -z "$(git ls-files --others --exclude-standard -- "$path")" ]]; then
  exit 0
fi

echo "$path is out of date: $hint" >&2
git status --short -- "$path" >&2
exit 1
