#!/usr/bin/env bash
# L3 Hook | PreToolUse (Bash)
# Block git commit/push carrying an AI Co-authored-by trailer.
# ADK Verification rule 6 + repo policy: commits are authored solely by the user.
python -c '
import sys, json, re
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (d.get("tool_input", {}).get("command") or "")
low = cmd.lower()
is_git_write = ("git" in low) and ("commit" in low or "push" in low)
if is_git_write and re.search(r"co-authored-by:.*(claude|anthropic|\[bot\])", low):
    sys.stderr.write(
        "Blocked: commits must not carry an AI Co-authored-by trailer "
        "(ADK Verification rule 6 + repo policy). Remove the "
        "Co-authored-by: Claude/AI line; commits are authored solely by the user."
    )
    sys.exit(2)
sys.exit(0)
'
