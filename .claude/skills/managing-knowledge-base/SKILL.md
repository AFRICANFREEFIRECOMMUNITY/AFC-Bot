---
name: managing-knowledge-base
description: Knows the AFC bot's three knowledge layers (auto-scraped knowledge_base.txt, curated knowledge/, staff-only knowledge_staff/), which one to touch for a given change, and how to add/list/remove curated docs via upload_docs.py — use when adding facts the bot should know, fixing wrong/missing answers, updating tournament/rules/FAQ content, putting staff-only info in, or refreshing the scraped website knowledge.
---

# Managing the AFC bot's knowledge base

The bot grounds every reply in three knowledge sources. All three are loaded **fresh on every reply** — no bot restart is needed after a content change; the next message picks it up. Pick the right layer before touching anything.

## The three layers

### 1. `knowledge_base.txt` — auto-scraped. DO NOT hand-edit.
Scraped from africanfreefirecommunity.com. It is regenerated automatically:
- GitHub Actions (`.github/workflows/update_knowledge.yml` → `scripts/scrape_knowledge.py`) every 3 hours, which commits any change.
- `auto_scrape_loop` (`bot.py:269`) inside the running bot every 6 hours (`SCRAPE_INTERVAL_HOURS = 6`, `bot.py:75`).

Any hand-edit is overwritten by the next scrape, so editing it is pointless. **Never put curated content here.** A PreToolUse guardrail (`.claude/hooks/block-knowledge-base-edit.sh`) also blocks edits to it outright.

To refresh the scraped base on demand (e.g. the site changed and you don't want to wait for the schedule):
```bash
python scrape_site.py
```
This rewrites `knowledge_base.txt` from the live site. No restart needed — the bot reads disk on the next reply.

### 2. `knowledge/` — curated, hand-written knowledge. This is where you add facts.
This is the **correct place for any hand-written content** (FAQ answers, rules, clarifications the scrape misses). Loaded by `load_knowledge()` (`bot.py:844`). The loader handles multiple formats placed in the folder: PDF via `pdfplumber`, Word `.docx` via `mammoth`, Excel `.xlsx` via `openpyxl`, and plain `.txt`.

Manage it with `upload_docs.py` (do not move files in by hand — use the script so extraction happens):
```bash
python upload_docs.py path/to/file.txt        # add a .txt
python upload_docs.py path/to/file.pdf        # add a PDF (extracted to .txt at upload time)
python upload_docs.py                          # list current docs
python upload_docs.py --remove file.txt        # remove a doc
```
`upload_docs.py` accepts only `.txt` and `.pdf` as input. For `.docx`/`.xlsx`, place the file directly in `knowledge/` — the runtime loader reads those formats even though the upload script does not ingest them.

### 3. `knowledge_staff/` — staff-only facts.
Loaded by `load_staff_knowledge()` (`bot.py:927`) and injected into the system prompt **only** when the message author has a role in `STAFF_KNOWLEDGE_ROLES`. The system prompt carries a hard rule never to reveal this content to non-staff. Put anything privileged here, never in `knowledge/`.

## How to choose
- Fact is on the AFC website and just stale → run `python scrape_site.py` (or wait for the loop). Do not edit `knowledge_base.txt`.
- Fact the bot should know but isn't scrapable (clarification, FAQ, rules, corrections) → add a doc to `knowledge/` via `upload_docs.py`.
- Fact only staff should ever see → drop it in `knowledge_staff/`.

## Do not
- Do not hand-edit `knowledge_base.txt` — it is regenerated on a schedule (GitHub Actions every 3h, `auto_scrape_loop` every 6h) and any edit is overwritten.
- Do not put curated or staff content in `knowledge_base.txt`.
- Do not restart the bot after a content change — all three layers reload on every reply.
- Do not drag files into `knowledge/` to add a `.txt`/`.pdf`; use `upload_docs.py` so PDFs get extracted.
