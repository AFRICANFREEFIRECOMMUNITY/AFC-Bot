#!/usr/bin/env bash
# L3 Hook | PreToolUse (Edit|Write|MultiEdit)
# Block hand-edits to knowledge_base.txt. That file is auto-scraped
# (GitHub Actions every 3h + auto_scrape_loop every 6h) and any manual edit
# gets overwritten. Curated, hand-written knowledge belongs in knowledge/.
# Reads the hook JSON payload on stdin; exit 2 = block (stderr shown to Claude).
python -c '
import sys, json, os
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
p = (d.get("tool_input", {}).get("file_path") or "")
base = os.path.basename(p.replace(chr(92), "/"))
if base == "knowledge_base.txt":
    sys.stderr.write(
        "Blocked: knowledge_base.txt is auto-scraped and will be overwritten by "
        "the next scrape (GitHub Actions every 3h / auto_scrape_loop every 6h). "
        "Put curated, hand-written knowledge in the knowledge/ folder instead "
        "(python upload_docs.py path/to/file)."
    )
    sys.exit(2)
sys.exit(0)
'
