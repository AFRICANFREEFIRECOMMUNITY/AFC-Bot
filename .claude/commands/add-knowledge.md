---
description: Add a curated document to the bot's knowledge/ folder
argument-hint: path/to/file.(txt|pdf)
allowed-tools: Bash(python upload_docs.py:*)
---

Add a curated document to the live `knowledge/` folder via `upload_docs.py`:

- Add: `python upload_docs.py $ARGUMENTS`
- List current docs: `python upload_docs.py`
- Remove: `python upload_docs.py --remove <filename>`

`knowledge/` is the right place for hand-written knowledge — NEVER `knowledge_base.txt` (auto-scraped, overwritten). The bot reads `knowledge/` live, so no restart is needed. `upload_docs.py` ingests `.txt` and `.pdf`; for `.docx`/`.xlsx`, place the file directly in `knowledge/` (the runtime loader reads those formats).

If `$ARGUMENTS` is empty, just list the current docs.
