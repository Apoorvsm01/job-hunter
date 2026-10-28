#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)

usage() {
  cat << 'EOF'
Usage: sh scripts/switch_agent.sh [antigravity | claude | both | status]

Easily toggle or enable agent configurations without affecting application code.

Commands:
  antigravity  Enable Antigravity (.agents/, GEMINI.md) and disable Claude (.claude/)
  claude       Enable Claude (.claude/, CLAUDE.md) and disable Antigravity (.agents/)
  both         Enable both Antigravity and Claude simultaneously (they do not conflict)
  status       Show current activation status for both runtimes
EOF
}

target="${1:-status}"

cd "$repo_root"

status() {
  echo "=== Agent Connection Status ==="
  if [ -d ".claude" ]; then
    echo "  Claude:      ENABLED (.claude/ active)"
  elif [ -d ".claude.disabled" ]; then
    echo "  Claude:      DISABLED (.claude.disabled)"
  else
    echo "  Claude:      NOT INSTALLED"
  fi

  if [ -d ".agents" ]; then
    echo "  Antigravity: ENABLED (.agents/ active)"
  elif [ -d ".agents.disabled" ]; then
    echo "  Antigravity: DISABLED (.agents.disabled)"
  else
    echo "  Antigravity: NOT INSTALLED"
  fi
  echo "==============================="
}

enable_antigravity() {
  if [ -d ".agents.disabled" ]; then
    mv .agents.disabled .agents
    echo "Restored .agents/ from .agents.disabled"
  fi
  if [ ! -d ".agents" ]; then
    mkdir -p .agents/skills
    for s in job-hunter job-scout job-reviewer job-radar job-feedback onboard-source; do
      if [ -d "skills/$s" ] && [ ! -e ".agents/skills/$s" ]; then
        ln -s "../../skills/$s" ".agents/skills/$s"
      fi
    done
    echo "Created .agents/skills"
  fi
  if [ -e "GEMINI.md.disabled" ]; then
    mv GEMINI.md.disabled GEMINI.md
  fi
  if [ ! -e "GEMINI.md" ] && [ -e "CLAUDE.md" ]; then
    ln -s CLAUDE.md GEMINI.md
  fi
}

disable_antigravity() {
  if [ -d ".agents" ]; then
    mv .agents .agents.disabled
    echo "Disabled Antigravity (.agents -> .agents.disabled)"
  fi
  if [ -e "GEMINI.md" ]; then
    mv GEMINI.md GEMINI.md.disabled
    echo "Disabled GEMINI.md (renamed to GEMINI.md.disabled)"
  fi
}

enable_claude() {
  if [ -d ".claude.disabled" ]; then
    mv .claude.disabled .claude
    echo "Restored .claude/ from .claude.disabled"
  fi
}

disable_claude() {
  if [ -d ".claude" ]; then
    mv .claude .claude.disabled
    echo "Disabled Claude (.claude -> .claude.disabled)"
  fi
}

case "$target" in
  antigravity)
    enable_antigravity
    disable_claude
    echo "✓ Switched to Antigravity."
    status
    ;;
  claude)
    enable_claude
    disable_antigravity
    echo "✓ Switched to Claude."
    status
    ;;
  both)
    enable_antigravity
    enable_claude
    echo "✓ Enabled both Antigravity and Claude."
    status
    ;;
  status)
    status
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown command: $target" >&2
    usage
    exit 2
    ;;
esac

