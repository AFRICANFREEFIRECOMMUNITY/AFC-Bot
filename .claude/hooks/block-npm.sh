#!/usr/bin/env bash
# L3 Hook | PreToolUse (Bash)
# Block any npm invocation (machine-wide malware policy — see CLAUDE.md).
# Allows pnpm/bun/npx-free commands; matches npm only as a standalone token.
python -c '
import sys, json, re
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cmd = (d.get("tool_input", {}).get("command") or "")
if re.search(r"(^|[^A-Za-z0-9_])npm([^A-Za-z0-9_]|$)", cmd):
    sys.stderr.write(
        "Blocked: npm is forbidden on this machine (confirmed malware policy). "
        "Use pnpm (drop-in) or bun instead. See CLAUDE.md."
    )
    sys.exit(2)
sys.exit(0)
'
