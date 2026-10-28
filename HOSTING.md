# Hosting from GitHub

This repository has the bot entry point at its root. Connect the hosting service to `aranvvyo/gambling-bot`, select the `main` branch, and set the project/root directory to `/` (the repository root).

## Build and start

- Python: 3.11 or newer.
- Install command: `python -m pip install -r requirements.txt`
- Start command: `python bot.py`
- A `Procfile` is included for platforms that use process declarations: `worker: python bot.py`.
- No `runtime.txt` is included because the hosting provider is unspecified; select Python 3.11+ in its runtime settings. If a provider requires its own runtime manifest, follow that provider's current instructions.

## Required host environment

Set these in the provider's environment/secret settings, not in committed files:

- `DISCORD_TOKEN`: bot token, stored as a secret.
- `OWNER_USER_IDS`: comma-separated Discord user IDs allowed to perform owner-only actions.
- `ADMIN_USER_IDS`: comma-separated Discord user IDs permitted to administer the bot. Configure only trusted operators.
- `FAIRNESS_LOG_CHANNEL_ID`: channel ID where the bot can publish fairness commitments and reveals.
- `DATABASE_URL`: writable SQLite file path on the provider's persistent disk, for example `sqlite:////absolute/persistent/path/casino.db`. The built-in default `sqlite:///casino.db` uses the process directory and may be lost when a host rebuilds its container.

`DISCORD_GUILD_ID` is optional. Set it to a test server for guild-scoped command sync; leave it unset to use global command sync.

## Deposits and safety

Deposits are disabled by default. Leave `DEPOSITS_ENABLED=false` and `DEPOSITS_LIVE_VERIFIED=false` until Apirone credentials, rates, and live verification have been reviewed. The optional secret variables are `APIRONE_ACCOUNT_ID` and `APIRONE_TRANSFER_KEY`; both must be configured together. Set conversion rates and their source/timestamps only after review. Do not enable withdrawals: this project has no withdrawal provider/workflow and rejects `WITHDRAWALS_ENABLED=true`.

The bot uses one SQLite database and has a process lock. Run one bot worker only; do not scale to multiple replicas against the same database. The bot requires the Discord Message Content privileged intent because it supports prefix commands; enable it in the Discord Developer Portal.

## Local setup

Copy `.env.example` to an ignored `.env`, fill the required values, and run:

```sh
python -m pip install -r requirements.txt
python bot.py
```

For development tests, install `requirements-dev.txt` and run `python -m pytest -q`.
