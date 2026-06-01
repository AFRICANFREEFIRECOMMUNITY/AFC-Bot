---
name: bot-background-loops
description: Explains the AFC Discord bot's five background polling loops in bot.py (auto_purge, auto_scrape, news, event, ban) — their line numbers, intervals, AFC API endpoints, target channels, the seen_*.json dedup with first-boot snapshot seeding that stops restart re-spam, the top-level exception swallowing and "⚠️" debug prints, and the critical event-time pitfall (compute_time_status never derives live/ended from time; the backend "status" field is the only source of truth, and the removed "likely ENDED" loop must not return). Use when editing, debugging, or adding to any poll loop, announcement channel, dedup/seen-state, or event live/ended logic.
---

# Bot background loops

Five forever-running tasks are created in `on_ready()` (`bot.py:2286`) via `bot.loop.create_task(...)` at lines 2304-2308 — in this order: `auto_purge_loop`, `auto_scrape_loop`, `news_poll_loop`, `event_poll_loop`, `ban_poll_loop`. To add a new loop, define it next to its peers and register it here. Do not create a separate file.

API base for all polls: `AFC_API_BASE = "https://api.africanfreefirecommunity.com"` (`bot.py:93`).

## The five loops

| Loop | Line | Interval | Endpoint | Target channel(s) |
|---|---|---|---|---|
| `auto_purge_loop` | 203 | every 1h (`asyncio.sleep(3600)`, line 208); purges history entries older than `HISTORY_TTL_SECS` (24h, line 112) | none | n/a |
| `auto_scrape_loop` | 269 | `SCRAPE_INTERVAL_HOURS` = 6h (line 75); sleeps first (line 272) so startup scrape isn't doubled | re-scrapes site into `knowledge_base.txt` | n/a |
| `news_poll_loop` | 373 | `NEWS_POLL_INTERVAL_SECS` = 120s (2 min, line 78); slept at line 387 | `/auth/get-all-news/` | `NEWS_ANNOUNCEMENT_CHANNEL_ID` 1306247327840731157 (line 72) |
| `event_poll_loop` | 544 | `EVENT_POLL_INTERVAL_SECS` = 120s (line 79); slept at line 572 | `/events/get-all-events/` | `TOURNAMENT_ANNOUNCEMENT_CHANNEL_ID` 955773076786798643 (line 83) / `SCRIM_ANNOUNCEMENT_CHANNEL_ID` 1487971199454679050 (line 85) — picked by `is_scrim` |
| `ban_poll_loop` | 801 | `BAN_POLL_INTERVAL_SECS` = 60s (1 min, line 80); slept at line 815 | `/auth/get-admin-activities/` | `BAN_ANNOUNCEMENT_CHANNEL_ID` 1317799517084454932 (line 88) / `UNBAN_ANNOUNCEMENT_CHANNEL_ID` 1353759565543637062 (line 90) — picked by `parsed["is_ban"]` |

`event_poll_loop` does two jobs: posts NEW events AND announces status changes (the backend `status` field flipping, e.g. `pending` → `live`). It also unconditionally refreshes the module-level `_cached_events` (line 137) on every tick — `_cached_events = events` at lines 555 and 575. `format_live_events()` (line 1003) reads that cache to build the system prompt, so don't gate the cache refresh behind any dedup check. Note: external events (`event_type == "external"`) are never seeded into `seen` and are skipped for both new-event and status-change announcements (lines 558, 562, 582, 611).

`ban_poll_loop` only acts on actions in `BAN_ACTIONS = {"banned_team", "unbanned_team", "banned_player", "unbanned_player"}` (line 646).

## Dedup + first-boot snapshot seeding

Each announcing loop deduplicates against a `seen_*.json` file in `BASE_DIR`:
- `SEEN_NEWS_FILE` → `seen_news.json` (line 107), helpers `load_seen_news`/`save_seen_news` (282/293)
- `SEEN_EVENTS_FILE` → `seen_events.json` (line 108), helpers at 416/426
- `SEEN_EVENT_STATUSES_FILE` → `seen_event_statuses.json` (line 139) — tracks per-event status so a flip is detected once
- `SEEN_BAN_ACTIVITIES_FILE` → `seen_ban_activities.json` (line 109), helpers at 649/660

First-boot rule: when the seen-set is empty (fresh checkout / wiped state), each loop SEEDS it with the current snapshot and saves immediately — `news_poll_loop` at 379-384, `event_poll_loop` at 550-569 (which also seeds per-event statuses at 560-568 so no status-change fires on first boot), `ban_poll_loop` at 806-812 — THEN proceeds into the `while` sleep without announcing. This is why a restart does not re-spam every existing item. Preserve this seed-then-skip pattern in any new loop: seed the seen-set with what already exists, persist it, and only announce items that appear AFTER the seed.

## Failure handling + debugging

Every loop body is wrapped so a single bad poll never kills the loop: it catches at the top level and prints a `⚠️` line, then continues. Key markers: `news_poll_loop error` (411), `event_poll_loop error` (638), `ban_poll_loop error` (840), `Auto-scrape failed` (278), plus per-item post failures (`Failed to post ...` at 406/602/632/834) and fetch failures (`fetch_all_news` 313, `fetch_all_events` 445, `fetch_admin_activities` 688). When a loop seems silent or stuck, grep stdout / Heroku worker logs for `⚠️` — do not remove the swallow or let exceptions propagate, or one transient API hiccup will stop announcements permanently.

## EVENT-TIME PITFALL — read before touching event logic

The API's `event_date` / `event_time` is NOT a reliable match-start timestamp. It is often the registration deadline or just a listed date. Because of that:

- `compute_time_status()` (`bot.py:972`) NEVER returns "live" or "ended" from time alone. It returns exactly one of `"upcoming"`, `"starting_soon"`, `"date_passed"`, `"unknown"` (see returns at lines 986/993/996/999/1000). `"date_passed"` only means the listed date is behind us — it explicitly does NOT mean the event ended.
- The ONLY authoritative source for live/ended state is the backend `event["status"]` field. Live/ended announcements must be driven by `status` changes in `event_poll_loop`, never by time.

A "time-derived auto-announcement" loop that posted "Tournament likely ENDED" embeds once the listed date passed was REMOVED because it spammed false ended announcements. Do NOT re-add it, and do not add any equivalent that infers live/ended from `compute_time_status`, `date_passed`, or the clock. If you need ended detection, key it off the `status` field and the `seen_event_statuses.json` state.