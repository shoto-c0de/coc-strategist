#!/usr/bin/env sh
set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p .agents/skills .claude/skills

rm -rf .agents/skills/coc-strategist .claude/skills/coc-strategist
ln -s ../../skills/coc-strategist .agents/skills/coc-strategist
ln -s ../../skills/coc-strategist .claude/skills/coc-strategist

python3 -m pip install -r skills/coc-strategist/scripts/requirements.txt
