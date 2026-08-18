# This repository is ARCHIVED (2026-08-18)

**The AFC Discord bot now lives inside the AFC backend repository.**

    AFC-B/afcbot/

Nothing here is maintained any more. Do not open pull requests, and do not deploy from this
repository: the running bot is deployed from `AFC-B` as the systemd service `afc-bot`.

## Why it moved

The bot polls six endpoints of the AFC backend for tournaments, news and bans. While it lived in a
repository of its own, a serializer change in `AFC-B` could break this program with nothing to catch
it, and the two were deployed and versioned separately. One repository means one `git pull` updates
the bot and the API it depends on together.

## What changed in the move

* It runs as `afc-bot.service` (see `AFC-B/deploy/systemd/`), in its own virtualenv at
  `afcbot/venv`, rather than as a Heroku-style worker dyno.
* The 3-hourly knowledge scrape that used to run here as a GitHub Action, committing
  `knowledge_base.txt` back to this repository, is now a Celery beat task in `AFC-B`
  (`afc_bot.tasks.refresh_bot_knowledge`) that writes the file to disk instead.
* It gained an authenticated HTTP control API, which backs the **Bot** page in the AFC admin
  dashboard (`/a/bot`). That is how the bot is managed now: channels, roles, intervals, knowledge
  documents and scrim approvals, without a shell.

## Where the history went

Everything in this repository is preserved. The final state, including the control API, is on the
`feat/bot-control-api` branch here and is also the code that was copied into `AFC-B/afcbot/`.
