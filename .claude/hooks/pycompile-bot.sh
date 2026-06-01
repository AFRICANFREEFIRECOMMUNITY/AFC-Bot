#!/usr/bin/env bash
# L3 Hook | PostToolUse (Edit|Write|MultiEdit)
# After any edit to bot.py, syntax-check it with py_compile. If it fails,
# exit 2 so the error is fed straight back to Claude before it moves on.
# Project dir comes from $CLAUDE_PROJECT_DIR (set by Claude Code), with the
# hook payload's cwd as a fallback. python handles Windows paths natively.
python -c '
import sys, json, os, subprocess
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
p = (d.get("tool_input", {}).get("file_path") or "")
base = os.path.basename(p.replace(chr(92), "/"))
if base != "bot.py":
    sys.exit(0)
proj = os.environ.get("CLAUDE_PROJECT_DIR") or d.get("cwd") or os.getcwd()
botpath = os.path.join(proj, "bot.py")
if not os.path.exists(botpath):
    sys.exit(0)
r = subprocess.run([sys.executable, "-m", "py_compile", botpath],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.stderr.write("py_compile FAILED for bot.py after this edit:\n")
    sys.stderr.write(r.stderr or r.stdout or "(no output)")
    sys.exit(2)
sys.exit(0)
'
