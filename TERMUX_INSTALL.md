# Local Termux setup

```sh
pkg update -y
pkg install -y python unzip
mkdir -p ~/casino-local
unzip -q ~/discord-casino-bot-final-polished.zip -d ~/casino-local
cd ~/casino-local/discord-casino-bot-upgraded
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
nano .env
python bot.py
```

To download the ZIP to Termux, place `discord-casino-bot-final-polished.zip` in `~/` first. The lock file prevents a second bot instance from starting with the same `DATABASE_URL`; use only one process for this database. `DAILY_REWARD` defaults to 100 virtual credits and can be set to `0` to disable it.

Set the bot token in `.env`. In the Discord Developer Portal enable **Message Content Intent**. The bot needs permissions to view messages, send messages and embeds, attach files, and send DMs. New deposit invoices and live payment crediting are disabled by default. Keep `DEPOSITS_ENABLED=false` and `DEPOSITS_LIVE_VERIFIED=false` until Apirone credentials, sourced current conversion rates for each network, credit limits, provider verification, and the live integration have been safely reviewed. This package has not been tested against a live Discord session or live payment endpoint. Message Content Intent must be enabled in the Developer Portal for prefix commands.

Game-result PNGs are rendered in memory with the Python standard library. Pillow and additional native image packages are not needed.

Persistent command prefix, emoji mappings, maintenance state, economy limits, daily reward, deposit limits/rates, currency label, branding, and log channel routes are stored in SQLite configured by `DATABASE_URL`. Back up that database before replacing the installation. The admin dashboard is available as `/admin-dashboard` or with the active prefix, for example `.admin-dashboard`.
