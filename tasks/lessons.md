# Lessons

## 2026-07-02 — Support channel is human-help only, never an activity venue

**Correction:** Bot answered "Guys where do I recruit players for my new team" by telling the
user to recruit **in `#moderation-and-support`** (the support channel). Wrong — that channel is
for human escalation, not a place to perform an activity.

**Root cause (prompt, not code):** `build_system_prompt()` had a very strong "always refer people
to the support channel when stuck" rule, but **no** rule naming the real recruitment venue. GPT
hit a question it couldn't answer from an obvious rule, dumped it onto the support channel, and
then mislabeled that channel *as the answer* ("recruit ... in #moderation-and-support").

**Rules for myself:**
1. The support/moderation channel is **human help / escalation ONLY**. Never present it as a
   feature, a venue, or the answer to a "where/how do I do X" question. It is the *fallback* for
   human help, not the destination for an activity.
2. When a "where do I do X" question has a real platform venue, the fix is to **add/point to that
   venue in `build_system_prompt()`** — don't let the support-channel default swallow answerable
   questions. Recruitment → **AFC Player Market** (`/a/player-markets`): Team Listings → Create
   Listing (teams), Player Listings → List Yourself (free agents). Also Teams page → Apply to Join.
3. When two curated KB files contradict (here: `knowledge_AFC_Current_Systems.txt` said
   "Player Markets: Coming Soon" vs `knowledge_AFC_Support_Guide.txt` describing a live transfer
   system), resolve against the **most detailed/authoritative doc + freshly-scraped signals**
   (glossary defines the player market as live; privacy policy stores "trial chat between player
   and team" — you don't write privacy policy for a nonexistent feature). Then fix the stale line.

**Verified:** `py_compile` OK; prompt-auditor PASS on all five guardrails; drove the live reply
pipeline with the exact broken message → now answers with the Player Market flow, support channel
only as the inline human-help fallback.
