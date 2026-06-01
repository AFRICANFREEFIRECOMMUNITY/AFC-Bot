---
name: deploying-the-bot
description: Explains how to run and deploy the AFC Discord bot — local run (python bot.py), production worker dyno via Procfile, Oracle Cloud Always Free provisioning via deploy/oracle/ (cloud-init.yaml, setup.sh, retry-create-a1.sh), required .env secrets (DISCORD_TOKEN, OPENAI_API_KEY), the Message Content Intent requirement, and the py_compile pre-ship check. Use when asked to run, deploy, ship, redeploy, provision, host, restart, or set up the bot anywhere.
---

# Deploying the AFC bot

Single-file bot (`bot.py`). No build step. Three ways to run it: locally, as a worker dyno, or on an Oracle Cloud Always Free VM via `deploy/oracle/`.

## Before you ship — always

Run the syntax check after ANY edit to `bot.py`. This is non-negotiable; a broken `bot.py` takes the whole bot down with no UI to catch it.

```bash
python -m py_compile bot.py
```

If it errors, fix it before deploying. There are no tests and no linter — `py_compile` is your only static gate.

## Required environment

Both secrets are loaded from `.env` via `python-dotenv`. The bot will not start without them.

```
DISCORD_TOKEN=...
OPENAI_API_KEY=...
```

`.env` is never committed and never logged. Also enable the **Message Content Intent** in the Discord Developer Portal (Bot → Privileged Gateway Intents) — without it the bot receives empty message bodies and the classifier/reply pipeline does nothing.

## 1. Local run

```bash
python bot.py
```

Reads `.env` from the repo root. Knowledge (`knowledge_base.txt`, `knowledge/`, `knowledge_staff/`) is loaded fresh on every reply, so editing curated docs needs no restart. The five background loops (auto_purge, auto_scrape, news_poll, event_poll, ban_poll) start in `on_ready` and seed their `seen_*.json` snapshots on first boot.

## 2. Production — worker dyno

`Procfile` is just:

```
worker: python bot.py
```

A Heroku-style worker dyno (no web process, no port). Set `DISCORD_TOKEN` and `OPENAI_API_KEY` as config vars on the platform rather than committing `.env`. Scale the worker to exactly one instance — running two copies double-posts every announcement, since dedup state (`seen_*.json`) is local per process and not shared.

## 3. Oracle Cloud Always Free (Ampere A1)

Everything lives in `deploy/oracle/`. The bot runs as a `systemd` unit named `afc-bot` under user `ubuntu` at `/home/ubuntu/AFC-Bot`, using a venv at `.venv` and Python 3.11 (deadsnakes PPA).

### First-boot provisioning — `cloud-init.yaml`
Paste the entire file (including the `#cloud-config` first line) into Oracle Console → Create Instance → Show Advanced Options → Management → User Data. It installs Python 3.11 + system deps (ffmpeg, libopus, libnacl, etc.), clones the repo, and runs `setup.sh`. It seeds an **empty** `.env` — the bot will not fully start until you fill it.

After the instance is up:
```bash
# SSH in, then fill secrets and start
nano /home/ubuntu/AFC-Bot/.env          # set DISCORD_TOKEN + OPENAI_API_KEY
sudo systemctl restart afc-bot
```

### Provision / redeploy script — `setup.sh`
Idempotent; run as root.
```bash
sudo bash setup.sh              # first-time install (packages, venv, requirements, systemd unit)
sudo bash setup.sh --update     # git fetch + reset --hard origin/main + reinstall + restart
```
It installs system packages, creates `.venv`, installs `requirements.txt`, writes the hardened `afc-bot.service` unit (`Restart=always`, `EnvironmentFile=.env`, `ProtectHome=read-only` with `ReadWritePaths` on the app dir), enables the service, and restarts it only if `.env` already has a `DISCORD_TOKEN`. If secrets are missing it tells you to fill `.env` and restart manually.

Operate the service:
```bash
sudo systemctl restart afc-bot
sudo systemctl status afc-bot --no-pager
sudo journalctl -u afc-bot -f      # follow logs; background-loop failures print "⚠️" lines here
```

### Capacity-restricted home region — `retry-create-a1.sh`
Oracle's free A1 shape is frequently "Out of host capacity" in a region. This script loops `oci compute instance launch` (VM.Standard.A1.Flex, 1 OCPU / 6 GB), sleeping 60s between attempts until one succeeds, then waits for state `RUNNING`. Requires the OCI CLI with a configured profile. Before running, fill the placeholder variables at the top: `COMPARTMENT_OCID`, `SUBNET_OCID`, `IMAGE_OCID` (Ubuntu 22.04 Aarch64), `AVAILABILITY_DOMAIN`, `SSH_PUBKEY_FILE`. It passes `cloud-init.yaml` as `--user-data-file`, so a successful launch auto-provisions via the cloud-init flow above.
```bash
bash retry-create-a1.sh
```

## 4. AWS (EC2 / Lightsail) + auto-deploy on push

`setup.sh` is cloud-agnostic Ubuntu 22.04, so AWS reuses it as-is. Full runbook: [`deploy/aws/README.md`](../../../deploy/aws/README.md).

- **Host:** an **Ubuntu 22.04** EC2 `t3.micro` (free tier) — NOT Amazon Linux (the script needs `apt` + deadsnakes + the `ubuntu` user). Lightsail ($5/mo) is the same thing. Provision via `deploy/aws/cloud-init.yaml` (User data) or by running `setup.sh` manually. Allocate an **Elastic IP** so the address is stable.
- **Security group:** outbound only for the bot itself; inbound just SSH (22) — from your IP for admin, and reachable by GitHub Actions runners for the deploy.
- **Auto-deploy:** `.github/workflows/deploy-aws.yml` fires on push to `main`, SSHes in with a dedicated deploy key, and runs `setup.sh --update`. Needs three repo secrets: `EC2_HOST`, `EC2_USER` (`ubuntu`), `EC2_SSH_KEY` (private deploy key). It uses `paths-ignore: knowledge_base.txt` so the 3-hourly knowledge auto-commit does not trigger a needless restart.
- **Why `--update` uses `git reset --hard origin/main`:** the running bot rewrites the tracked `knowledge_base.txt`, leaving the tree dirty so a plain `pull` fails. `reset --hard` makes git authoritative and only touches tracked files — the gitignored, untracked `seen_*.json` / `conversation_history.json` survive, so dedup state is preserved and no announcements re-spam.
- **Runtime-state hygiene:** `.gitignore` excludes `.env`, `conversation_history.json`, `seen_*.json`, `__pycache__/`, `.venv/`. `knowledge_base.txt` stays tracked on purpose (committed + refreshed by the Action).

## Knowledge workflow runs on its own schedule — leave it alone

`.github/workflows/update_knowledge.yml` runs `scripts/scrape_knowledge.py` every 3 hours (`cron: '0 */3 * * *'`, plus manual `workflow_dispatch`) and commits any change to `knowledge_base.txt`. It is independent of however you deploy the bot — you do not trigger or coordinate it as part of a deploy. **Never hand-edit `knowledge_base.txt`**; the next scheduled scrape overwrites it. Curated content goes in `knowledge/` (via `upload_docs.py`).

## Deploy checklist

1. `python -m py_compile bot.py` passes.
2. Secrets present (`.env` locally, config vars on a dyno, filled `.env` on the Oracle VM).
3. Message Content Intent enabled in the Discord Developer Portal.
4. Exactly one bot process running (more than one double-posts announcements).
5. Tail logs after start (`sudo journalctl -u afc-bot -f` on Oracle) and confirm `on_ready` fired with no top-level loop `⚠️` errors.