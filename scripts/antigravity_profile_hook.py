#!/usr/bin/env python3
"""Antigravity PostToolUse hook adapter to auto-diff candidate_profile.yaml on edits."""

import json
import subprocess
import sys
from contextlib import suppress
from pathlib import Path


def run(payload: dict, repo_root: Path) -> None:
    # Check tool call / input arguments for TargetFile or file_path
    tool_call = payload.get("toolCall") or {}
    args = tool_call.get("args") or payload.get("tool_input") or {}
    target = args.get("TargetFile") or args.get("file_path") or args.get("path") or ""

    if not target or not isinstance(target, str):
        return

    edited = Path(target).expanduser()
    if not edited.is_absolute():
        edited = repo_root / edited

    target_profile = (repo_root / "config/candidate_profile.yaml").resolve()
    if edited.resolve() != target_profile:
        return

    if payload.get("error"):
        return

    # Run profile diff report in the background/quietly
    subprocess.run(
        ["python3", "scripts/diff_profile.py"],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    with suppress(Exception):
        if not sys.stdin.isatty():
            data = json.load(sys.stdin)
            if isinstance(data, dict):
                run(data, repo_root)
    # PostToolUse requires a JSON object on stdout
    print("{}")

