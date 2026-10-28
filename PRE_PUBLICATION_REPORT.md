# Pre-publication report — Discord Casino Bot

**Audit date:** 2026-10-27
**Source audited:** `/data/data/com.termux/files/home/discord-casino-bot` and the existing `discord-casino-bot.zip` available beside it.
**Release status:** Hosting package prepared; **not approved for real-money/public casino launch**.

## Executive summary

The existing source contains an asynchronous `discord.py` application with nine games, an SQLite wallet/ledger, Apirone invoice polling, deterministic fairness records, admin controls, and Discord/local event logging. The previous ZIP wrapped all files in a `discord-casino-bot/` directory, so a panel that extracts into its configured working directory would not find `bot.py` at the root without changing directories. The source entry point also referenced `os.chmod` without importing `os`, which prevented startup before configuration validation.

This release fixes that entry-point failure, makes missing-token startup exit with a short non-secret configuration message, creates configured SQLite parent directories, rejects an empty SQLite path, documents generic Python panel deployment, updates the stale release checklist, and puts project files at the ZIP root. A provider-specific panel file was not added because no hosting provider was named.

## Project history (historical reports vs current audit)

- The original request described a Python Discord casino with Apirone deposits, a persistent wallet, Mines, Blackjack, Dragon Tower, Crash, and a Limo game to be identified from the supplied project context.
- Later project requests expanded the existing bot to include Limbo and priority additions Dice, Chicken Road, and Pump. The current source documents nine games total and treats Pump Chicken as overlapping with Chicken Road rather than creating a duplicate game.
- Earlier assistant reports described wallet/ledger hardening, restart refunds, deposit idempotency, Apirone network separation, fairness commitments/reveals, admin controls, and **51 passing tests**. Those earlier results are historical claims. The present source and latest available ZIP were independently inspected and rechecked for this report; the previous audited release reported 101 passing tests; this configuration release reruns the suite and reports its exact result below.
- This audit did not use a production database, send a cryptocurrency transaction, contact a live Apirone account, or connect to Discord.

## Current implementation observed

### Games

Mines, Blackjack, Dragon Tower, Crash, Limo, Limbo, Dice, Chicken Road, and Pump. Interactive games use Discord components and server-side state. Outcomes use `secrets`/seed-derived deterministic logic. Fair round records store a commitment, seed association, nonce, game, client seed, digest, and settlement outcome; `/fair-verify` verifies completed rounds after seed reveal. A restart refunds unsettled rounds rather than resuming their view state. Ordinary inactivity timeouts follow the game rules and settle as a loss.

### Slash commands loaded by the current cogs

`/casino`, `/help`, `/balance`, `/transactions`, `/profile`, `/deposit`, `/deposit-history`, `/deposit-status`, `/mines`, `/blackjack`, `/dragon-tower`, `/crash`, `/limo`, `/limbo`, `/dice`, `/chicken-road`, `/pump`, `/fairness`, `/fair-verify`, `/play-limit`, `/play-status`, `/self-exclude`, `/admin-config`, `/admin-credit`, `/admin-game`, `/admin-house-edge`, `/admin-limits`, `/admin-log-channel`, `/admin-maintenance`, `/admin-rate`, `/admin-status`, and `/admin-withdrawals`.

### Wallet, database, and payments

SQLite schema and migrations provide user balances, an append-only transaction ledger, deposit invoices, game sessions, player controls, fairness seeds/rounds, application settings, and admin audit records. Transactions use locking and unique references for balance changes and settlement. SQLite is the only adapter and is intended for one bot process. Apirone polling supports Litecoin (`ltc`), USDT on BNB Smart Chain (`usdt@bnb`), and USDT on Ethereum (`usdt@eth`) as distinct assets. Invoice confirmation and conversion rates are checked before automatic credit; zero/stale/source-less rates prevent automatic conversion credit. No withdrawal execution provider exists and withdrawals are forced off.

### Admin and logging

Admin commands require configured owner/admin IDs and Discord Administrator permission in guilds; owner-only operations include rate and log-route changes. Administrative configuration is persisted and audited. The eight channel routes are withdrawal, wins, deposit, bet, admin, security, error, and fairness. Financial records are stored in SQLite; Discord messages and local rotated logs supplement those records. The event queue and its deduplication cache are process-local, so Discord audit delivery is best-effort rather than a durable event queue.

### Configuration present in `.env.example`

Discord: `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `ADMIN_USER_IDS`, `OWNER_USER_IDS`, `ADMIN_CHANNEL_ID`.
Fairness: `FAIRNESS_ROTATION_SECONDS`, `FAIRNESS_LOG_CHANNEL_ID`.
Logging: `WITHDRAWAL_LOG_CHANNEL_ID`, `WINS_LOG_CHANNEL_ID`, `DEPOSIT_LOG_CHANNEL_ID`, `BET_LOG_CHANNEL_ID`, `ADMIN_LOG_CHANNEL_ID`, `SECURITY_LOG_CHANNEL_ID`, `ERROR_LOG_CHANNEL_ID`.
Economy/UI: `CASINO_NAME`, `CURRENCY_SYMBOL`, `MIN_BET`, `MAX_BET`, `MAX_PAYOUT`, `DAILY_BET_LIMIT`, `HOUSE_EDGE`, `MAINTENANCE_MODE`, `BRAND_COLOR`, casino/game image URL settings.
Database: `DATABASE_URL`.
Apirone: `APIRONE_ACCOUNT_ID`, `APIRONE_TRANSFER_KEY`, `APIRONE_INVOICE_LIFETIME`, `APIRONE_POLL_INTERVAL`, `MIN_DEPOSIT`, `MAX_DEPOSIT`, `MAX_DEPOSIT_CREDIT`.
Rates: `VC_PER_LTC`, `VC_PER_USDT_BEP20`, `VC_PER_USDT_ERC20`, matching rate update timestamps and source labels, and `VC_RATE_MAX_AGE_SECONDS`.
Withdrawals: `WITHDRAWALS_ENABLED` must remain `false`.

## Changes made in this hosting preparation

- `bot.py`: imported the missing `os` symbol required by startup log setup; missing `DISCORD_TOKEN` now exits with status 2 and a concise `Configuration error` message rather than an unhandled traceback.
- `database/db.py`: creates parent directories for configured file-backed SQLite paths before connecting. Existing database files are opened in place and are not reset.
- `config.py`: rejects a blank SQLite database path.
- `tests/test_hosting.py`: added missing-credential startup and persistent-path initialization regression tests.
- `tests/test_config.py`: added an empty database path validation regression test.
- `README.md`: added Python panel upload/extract, dependency install, startup, permissions, environment variables, persistent volume, restart, and backup guidance. Clarified generic panel requirements because no provider was specified.
- `RELEASE_CHECKLIST.md`: replaced stale contradictory notes with the actual tested scope and pre-publication checklist.
- `.gitignore`: ignores the release audit environment.
- `PRE_PUBLICATION_REPORT.md`: this report.
- ZIP layout: project contents are now at archive root (`bot.py`, `requirements.txt`, `cogs/`, `database/`, etc.), with no enclosing project folder. No source modules were removed or renamed; no user database was modified.


## Requested host configuration (2026-10-27)

Files changed for this configuration release: `config.py` (non-secret defaults, secret normalization, uncapped sentinel), `.env.example` (settings with blank secret values), `database/db.py` and `services/ui.py` (enforce `MAX_BET=0` as no per-bet cap), `cogs/admin.py` (admin limits UI supports/display uncapped mode), `README.md` (hosting and denomination notes), `tests/test_config.py` (configuration and wager regressions), and this report.

The following non-secret defaults are now centralized in `config.py` and mirrored in `.env.example`; environment values can override them: guild `1564670110164058324`, owner `1366824047534542910`, admin `1505906955271536671`, win log channel `1564689532899565568`, withdrawal log channel `1564689454311014491`, and admin log channel `1564689564398911559`. These load into command sync, owner/admin authorization, and the existing event-log channel routing. `MIN_BET=1` is the smallest supported whole VC unit. `MAX_BET=0` means no per-bet cap in the config, validator, wallet session, and admin limit command; the existing daily wager cap (`50,000 VC`) and payout cap still constrain play.

The current wallet stores integer virtual credits and has no VC/USD conversion for wager display. Therefore the requested `$0.01` is **not** asserted as a dollar-equivalent amount; a real denomination needs an explicit wallet unit and conversion policy. There is no withdrawal execution/request provider or wager-requirement feature in this project. No unsupported minimum-withdrawal setting was added; withdrawals remain disabled and cannot be enabled. Deposit credentials and the Discord token remain environment-only. The config example contains blanks for secrets; fill them in the host secret manager or a local ignored `.env`. Whitespace-only credentials are normalized to empty; partial Apirone credentials fail startup validation. Do not put credentials in this report or ZIP. Secrets shared in conversation were not written to files and must be rotated before use.

## Crypto deposit audit and fixes (2026-10-27)

Reviewed the actual invoice creation, Discord presentation, status refresh, poll loop, conversion calculation, database migration, and wallet credit path against current official Apirone docs: [Invoices](https://apirone.com/docs/invoices/), [Service info](https://apirone.com/docs/service/), and [Receiving callbacks](https://apirone.com/docs/callbacks/).

### Bugs and risks found and fixed

1. **Legitimate completed invoices could be held forever.** The old verifier treated every history row with `status=partpaid` as an unconfirmed transaction, even though Apirone history is a sequence of invoice status snapshots and the current authenticated invoice `completed` state represents required confirmations. It now accepts documented historical statuses, deduplicates repeated txids, and requires the current status to be `completed` plus the exact sum of unique transaction minor units.
2. **Late-confirming expired invoices stopped being polled.** Apirone docs state an invoice can expire while a sent/stuck transaction later confirms. Expired, uncredited invoices now remain pollable; terminal local `failed` entries are excluded. No funds are credited on `expired`.
3. **Minor-unit parsing could silently truncate malformed floats.** `int(1.9)` would become `1`, and booleans are Python integers. Provider invoice and history amounts now accept only integer JSON values or integer digit strings; floats, booleans, missing, negative, and zero transaction amounts fail closed.
4. **Database-level credit did not independently require exact verified units.** The deposits table now persists `verified_amount`; the credit transaction requires `completed`, an exact paid-unit total equal to requested units, and a transaction ID recorded from the provider history. Credit flag, balance increment, and ledger insertion remain atomic/idempotent.
5. **Invoice metadata was not stored or shown.** Creation now requires a future valid Apirone `expire` field, stores expiry and invoice URL, and displays expiry. Only an HTTPS invoice link on `apirone.com/invoice` is rendered.
6. **Provider response binding was too permissive.** Account matching was conditional and response address validation was only nonempty. Creation and polling now require the configured account, exact asset code/network, amount, invoice ID, and the same stored address; LTC has Base58Check/Bech32 shape and checksum validation, and EVM token networks require a 20-byte hex address. A successful provider response is required; there is no fallback address path.
7. **A failed invoice insert could leave a stray user row.** Invoice persistence is now in a database transaction and rolls back atomically on duplicate invoice IDs.
8. **The deposit panel lacked a status button and address-only copy context.** The ephemeral invoice view now has owner-scoped copy and status-refresh buttons; copied address text includes the asset/network and exact amount. Provider outages return a private safe message. Timed-out views disable stale controls. `/deposit-status` remains available.
9. **Asset precision was not covered by Apirone request-contract tests.** Official current service metadata specifies units factors of `1e-8` for LTC, `1e-18` for USDT BEP20, and `1e-6` for USDT ERC20. The code mapping matches these values. Current documentation lists minimum confirmations of 1, 4, and 64 respectively; only the authenticated current invoice `completed` status is used as the confirmation decision.
10. **Credentials could be partially configured with no clear startup error.** Configuration now requires Apirone account ID and transfer key together. If both are absent, deposit commands report unavailable and no address is generated.

Apirone's documented invoice callback payload has account, invoice, and status but no signature field; callbacks are intentionally not enabled. Private polling uses the documented `/api/v2/accounts/{account}/invoices/{invoice}` endpoint and `transfer-key` query parameter. A local/adapter `failed` status is handled as terminal/no-credit, but Apirone's published invoice status set does not list `failed`; unknown future statuses are rejected safely.

### Deposit test coverage added

Mocked tests now cover the documented creation endpoint and amount serialization for all three assets, response account/currency/address/amount/status/expiry checks, private polling endpoint/auth parameter and timeout suppression, malformed JSON/HTTP errors, partial history snapshots, duplicate txids, current status gating, exact/under/overpayment totals, malformed amounts/txids, stale rates, expired invoice re-polling, failed adapter status, concurrent repeated polling with one credit, direct DB exact-unit credit guard, duplicate invoice rollback, address formats, all three conversion scales, deposit button ownership/status refresh/provider errors/timeouts, the three asset choices, and migration preservation of old invoice data.

**Live integration remains unverified:** no Apirone credentials or safe provider test account were available. No real invoice was issued and no address was generated by the live provider in this audit. The addresses used in tests are mock fixtures only and are never shown by a production fallback.

## Verification performed

Environment: Python **3.14.8** on Android/Termux. Dependencies were installed from `requirements.txt` in a clean virtual environment for the extracted release.

- `python -m pip check`: passed (`No broken requirements found`).
- `python -m compileall -q bot.py cogs database games services tests`: passed.
- Final source and extracted ZIP: `python -m pytest -q` results are recorded in the configuration release verification section below.
- Loaded all 12 cogs and confirmed unique slash command names; the command inventory above was printed from the live command tree.
- Ran the entry point with `DISCORD_TOKEN` unset/blank: exited with code 2 and `Configuration error: DISCORD_TOKEN is required`; no traceback or token value was printed.
- Tested creation of a nested configured SQLite path using a temporary test database.
- Extracted the final ZIP into a separate directory, installed its dependencies in a new virtual environment, and reran dependency, compilation, cog-loading, and test checks.
- Ran `unzip -t` on the final archive and inspected its member list. Secrets, `.env`, database files, local logs, caches, and virtual environments are excluded.
- The two test warnings are `discord.py` internal use of deprecated `asyncio.iscoroutinefunction` under Python 3.14; they did not fail tests.

Not performed: live Discord login/interaction rendering, Discord permission validation in a real server, real Apirone invoice creation/status verification, crypto transaction, live conversion-rate lookup, deployment on a named hosting provider, or long-running production load/recovery test. Payment tests are mocked.

## Hosting guide

1. Upload `discord-casino-bot.zip` to the Python bot panel and extract it into the service working directory. The ZIP has `bot.py`, `requirements.txt`, and `.env.example` at its root; do not leave the files one directory below the configured working directory.
2. Select **Python 3.11+**. The audit ran under 3.14.8.
3. Enter environment variables in the panel's secret/configuration UI. Minimum setup for the bot to run and publish fairness commitments: `DISCORD_TOKEN`, `OWNER_USER_IDS`, and a `FAIRNESS_LOG_CHANNEL_ID` channel the bot can read and send to. Set `DISCORD_GUILD_ID` for test-guild command sync. Configure `ADMIN_USER_IDS` to delegate administration.
4. Set `DATABASE_URL` to the host's persistent writable volume, using SQLite URL form. Example format: `sqlite:////absolute/provider/persistent/path/casino.db`. The database parent directory is created automatically. Confirm with the provider that this path survives container rebuilds; the default relative `sqlite:///casino.db` is not guaranteed persistent.
5. Install dependencies with `python -m pip install -r requirements.txt`.
6. Set the panel launch command to **`python bot.py`** and working directory to the directory containing `bot.py`. `sh run.sh` is provided for VPS/Termux shell usage; it creates a venv and installs dependencies. No `package.json` is needed.
7. In Discord Developer Portal, enable the bot and invite with `bot` and `applications.commands` scopes. Grant View Channels, Send Messages, Embed Links, Attach Files, and Read Message History in game/log channels. This code does not require privileged Gateway intents.
8. Keep one process only. Back up with `python scripts/backup_db.py /secure/path/casino-backup.sqlite`; copy backups off-host and periodically test restore. Local logs may not persist across rebuilds. Restarted unsettled game wagers are refunded once; the games do not resume.

## Remaining requirements and risks before public release

- **Legal:** obtain jurisdiction-specific review of gambling licensing, age gates, consumer protection, responsible-play obligations, privacy, taxes, sanctions, and custody/payment rules. This package is not a legal compliance implementation.
- **Real deposits:** keep Apirone unconfigured or rates at zero until credentials, account settings, supported network precision, confirmation policy, invoice lifecycle, limits, and a controlled end-to-end test are approved. Current integration tests are mocks; no live payment verification is claimed. Apirone credentials belong only in host secret settings.
- **Withdrawals:** disabled and not implementable safely from the current code. A payout signer/provider, approval workflow, idempotency, reconciliation, limits, and security review would be required.
- **Fairness:** public commitments and post-settlement reveals depend on a properly permissioned, player-visible fairness channel. Independent tests cover deterministic records, but an independent game-math/security review and live Discord observation of commitment-before-play/reveal-after-settlement remain outstanding.
- **Persistence/recovery:** provider volume persistence is not verified. SQLite is single-process. Configure automated backups, off-host retention, restore drills, disk alerts, and a recovery owner before using valuable balances. Game state is not resumed after restart; unsettled wagers are refunded.
- **Monitoring/privacy:** Discord log delivery may fail and local logs can be ephemeral; monitor the process, fairness publication, ledger reconciliation, payment polling, disk/database errors, and audit delivery. Set access and retention rules for Discord IDs and payment metadata.
- **UI/runtime:** components were exercised by unit/cog tests, not visually inspected in live mobile and desktop Discord clients. Verify channel permissions and response latency in a staging server.
- **Rate source:** there is no exchange-rate oracle. Operators enter per-asset rates, source labels, and timestamps. Review and record rate policy independently.
- **Usage warning:** virtual-credit mode is the safe initial mode. Do not promise cash redemption or treat test credits as real funds.

## Pre-publication checklist

- [ ] Confirm legal review, minimum-age policy, responsible-play process, privacy notice, and jurisdiction availability.
- [ ] Deploy in a staging guild with test balances; verify command visibility, permissions, mobile/desktop layouts, logging routes, and timeouts.
- [ ] Independently review all game probabilities, house edge, payout caps, fair derivations, verifier records, seed commitment publication, and reveal timing.
- [ ] Configure host secrets; rotate any credentials that were ever exposed outside the hosting secret manager.
- [ ] Confirm provider persistent-volume semantics, set `DATABASE_URL`, keep one process, enable restart monitoring, and test backup restoration.
- [ ] Reconcile wallet ledger against balances and test duplicate payment/payout handling using fixtures only.
- [ ] Test fairness channel outage, event-log channel permission failure, database full/locked behavior, and bot restart in staging.
- [ ] Keep `WITHDRAWALS_ENABLED=false`.
- [ ] Keep real deposits disabled until Apirone account/network/confirmation/rate behavior receives controlled end-to-end verification and compliance approval.
- [ ] Configure alerts, log retention, incident response, and an owner responsible for daily reconciliation.

## Configuration release verification

This release adds regression tests for the configured IDs/channel routes, integer VC minimum, and uncapped-per-bet sentinel while preserving the original deposit tests. Clean-extracted release: Python 3.14.8, fresh virtual environment install from `requirements.txt`, `pip check` passed, compile checks passed, missing-token startup exited 2 with a safe message, command/cog registration passed, deposit UI tests passed, migrations exercised by migration-preservation tests, and ZIP `unzip -t` passed. Final full suite: **103 passed, 2 warnings**. The warnings are `discord.py` internal use of deprecated `asyncio.iscoroutinefunction` under Python 3.14. Discord live login and Apirone live invoice/payment verification were not performed. The Discord token and Apirone credentials provided in conversation were not written to the project or archive; rotate them before use because credentials pasted into chat must be treated as exposed.
