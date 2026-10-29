#!/usr/bin/env bash
# Install the identical skill directory used by the Claude Code plugin.
set -euo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--with-prompt" ) ]]; then
  echo "Usage: bash scripts/install-codex.sh [--with-prompt]" >&2
  exit 1
fi
source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
codex_root="${CODEX_HOME:-$HOME/.codex}"
skill_parent="$codex_root/skills"
skill_target="$skill_parent/said-it-twice"
if [[ -e "$skill_target" || -L "$skill_target" ]]; then
  echo "Refusing to overwrite $skill_target; archive the old installation first." >&2
  exit 1
fi
mkdir -p -- "$skill_parent"
python3 - "$source_root/skills/said-it-twice" "$skill_target" <<'PYTHON'
import shutil
import sys
shutil.copytree(sys.argv[1], sys.argv[2], ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
PYTHON
if [[ "${1:-}" == "--with-prompt" ]]; then
  prompt_parent="$codex_root/prompts"
  prompt_target="$prompt_parent/said-it-twice.md"
  mkdir -p -- "$prompt_parent"
  if [[ -e "$prompt_target" || -L "$prompt_target" ]]; then
    echo "Skill installed. Existing custom prompt left untouched: $prompt_target" >&2
  else
    cp -- "$source_root/codex/prompts/said-it-twice.md" "$prompt_target"
  fi
fi
printf 'Installed said-it-twice at %s. Restart Codex, then use $said-it-twice.\n' "$skill_target"
