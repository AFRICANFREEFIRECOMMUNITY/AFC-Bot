---
description: Re-scrape the AFC website into knowledge_base.txt
allowed-tools: Bash(python scrape_site.py)
---

Run `python scrape_site.py` from the repo root to re-scrape africanfreefirecommunity.com into `knowledge_base.txt`.

The bot reads knowledge from disk on every reply, so no restart is needed. After it runs, confirm the scrape succeeded and summarize what changed (diff `knowledge_base.txt`). Do NOT hand-edit `knowledge_base.txt` — it is regenerated on a schedule and your edits would be overwritten.
