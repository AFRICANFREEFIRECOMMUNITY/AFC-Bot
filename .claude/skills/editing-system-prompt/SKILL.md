---
name: editing-system-prompt
description: Knows how to change the AFC Discord bot's reply behavior, tone, and wording by editing build_system_prompt() in bot.py rather than writing code. Use whenever someone says "fix the bot," "it said the wrong thing," "change how it talks/answers," "make it stop/start saying X," "it gave a wrong link," "it didn't escalate," or any request about what the bot replies — these are almost always prompt edits, not code changes.
---

# Editing the AFC bot's system prompt

Most "fix the bot's behavior" requests are edits to the system prompt, not code. The reply text the bot produces is governed by `build_system_prompt(is_staff)` @ `bot.py:1045`. Start there.

## Why the prompt, not code

The reply pipeline has two stages:

1. **Classifier** — `should_bot_respond()` @ 2367 (`gpt-4o-mini`, 5-token answer) decides *whether* to reply. It **defaults to YES on any error** — intentional, never miss a real question. Do not change that.
2. **Reply** — `ask_openai_text()` @ 1423 and `ask_openai_with_image()` @ 1455 (`gpt-4o`) produce *what* the bot says. Both build the system prompt fresh by calling `build_system_prompt(is_staff=...)` on every single call.

Because the prompt is assembled fresh each call, **changing the prompt changes behavior immediately on the next message — no restart, no migration.** The prompt is the product. If the bot says something wrong, picks the wrong tone, refuses to escalate, or recommends the wrong thing, the rule that produced it almost certainly lives in the text inside `build_system_prompt()`.

## How to make a change

1. Read `build_system_prompt()` @ 1045 in full. It is organized as numbered rules and interpolated sections (loaded knowledge, `format_live_events()`, constants like `AFC_DISCORD_INVITE` and `SUPPORT_CHANNEL_ID`).
2. **Reproduce in your head the exact message that misbehaved.** Walk the prompt rule-by-rule and find which rule (or missing rule) caused the bad output. Name it before editing.
3. Edit **surgically** — change or add the one rule that owns the behavior. Do not rewrite the prompt, do not reorder unrelated rules, do not "clean it up." Rules here have history; many exist because GPT got something wrong before.
4. Reason forward: with your edited text, would the bad message now produce the right reply? Would a *good* message still work? Check you didn't break an adjacent rule.
5. Syntax-check: `python -m py_compile bot.py`.

## The needs_support tuple contract

`ask_openai_text()` @ 1423 returns a **tuple `(reply, needs_support)`**. It detects the literal marker `---SUPPORT_REDIRECT---` in the model output (`needs_support = "---SUPPORT_REDIRECT---" in raw` @ 1445), strips it from the reply (@ 1446), and returns the bool. The caller must use **both** elements and, when `needs_support` is True, call `send_support_redirect()` @ 1499 (posts a separate embed pointing at `<#SUPPORT_CHANNEL_ID>` and pings `SUPPORT_ROLES`).

Note: `ask_openai_with_image()` @ 1455 returns a **plain string** and does *not* strip the marker or return the flag. If you add a new code path that calls `ask_openai_text()`, handle both tuple elements and wire up `send_support_redirect()`. Don't route `needs_support` through exceptions — it flows through the return value only.

## Hard rules — NEVER weaken these

These are enforced by text inside `build_system_prompt()`. Editing the prompt must never loosen any of them:

- **Discord invite.** `AFC_DISCORD_INVITE = "https://discord.gg/qgKKZMu4sA"` @ 97 is the *only* invite/Discord URL the bot may ever output. The CRITICAL rule against emitting any other Discord URL exists because GPT used to hallucinate fake invite codes. **Do not soften, generalize, or remove this rule.** If a request would let the bot produce a different Discord link, push back.
- **Two distinct support mechanisms — do not conflate.**
  (a) *Inline mention* of the support channel in the reply text — use generously, any time the bot can't fully resolve something. No ping, no marker.
  (b) *Hard escalation* — the `---SUPPORT_REDIRECT---` marker @ 1107, reserved only for cases where a human must take direct action on the platform. It pings the support roles via `send_support_redirect()`. Never make the marker the default for "I don't know"; that's what mechanism (a) is for.
- **Staff-knowledge secrecy.** Staff knowledge is injected only when `is_staff=True`. The prompt has a hard rule to never reveal staff knowledge to non-staff. Don't add anything that would leak it or relax that boundary.
- **Classifier defaults to YES on error** (`should_bot_respond()` @ 2367) is intentional. Don't change it as part of a "behavior fix."

## What not to do

- Don't write code to fix something a prompt rule can fix.
- Don't hand-edit `knowledge_base.txt` (auto-overwritten by the scrape loop and GitHub Actions). Curated content goes in `knowledge/` via `upload_docs.py`.
- Don't split prompt logic into new files — keep it in `build_system_prompt()` @ 1045.
- Don't claim done without `python -m py_compile bot.py` passing and reasoning through the originally-broken message against your new prompt text.
