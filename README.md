# Velvet Vault — Discord Casino Bot

An asynchronous Python 3.11+ Discord casino bot with a SQLite wallet, auditable ledger, interactive games, Apirone invoice polling, and deterministic fair-round records. The default currency is simulated virtual credits (VC); withdrawals and cash redemption are disabled. Review gambling, consumer-protection, tax, sanctions, and age requirements before enabling any real deposits.

## Features

- Slash commands, private game views, buttons, selects, modals, embeds, responsive Discord components, local SVG game art, optional configured image URLs, and private administrative commands.
- Games: Mines, Blackjack, Dragon Tower, Crash, Limo, Limbo, Dice, Chicken Road, and Pump. Game results and wallet changes are server controlled.
- SQLite transactions use `BEGIN IMMEDIATE`, unique ledger references, wager locks, idempotent settlement, payout caps snapshotted when a wager starts, and startup refunds for unsettled sessions.
- Admin permissions require an allowlisted ID plus Discord Administrator permission in guilds. Owner-only actions include conversion-rate and log-route changes. Sensitive responses are ephemeral; all configuration writes are audited.
- Withdrawals are hard-disabled because there is no signing provider, approval lifecycle, or transaction reconciliation adapter.

“Pump Chicken” does not appear as a distinct game in the supplied project references; the project documents it as overlapping with Chicken Road, so no duplicate game was added.

## Rules and payout calculations

Integer VC payouts round down and respect the round’s payout cap. The global disclosed house edge is configurable from 0% to 25%; it is snapshotted at the start of interactive games so a later admin change cannot alter an active wager.

- **Dice:** outcome is a deterministic roll from 0–99. Under wins for `roll < target`; over wins for `roll > target`. The winning probability is `target/100` for under and `(99-target)/100` for over. An impossible zero-probability target is rejected. Multiplier is `(1-edge)/probability`, rounded down to 0.01×.
- **Mines:** 16- or 20-tile board; 1 to `board_size-1` mines. After `k` safe selections, multiplier is `[(N × … × (N-k+1))/((N-m) × … × (N-m-k+1))] × (1-edge)`, rounded down to 0.01×. Cash out after at least one safe tile.
- **Dragon Tower:** 2 or 3 paths, 1–12 floors, one safe path each floor. At `n` safe floors the multiplier is `paths^n × (1-edge)`, rounded down to 0.01×. Cash out after a safe floor.
- **Blackjack:** dealer stands on soft 17, no split or insurance, double down only before a hit. Push returns the wager; a natural pays 3:2; other wins pay 1:1 profit. Dealer natural settles immediately.
- **Crash:** multiplier rises at 0.35× per second from 1.00×. The crash point is sampled from `P(crash ≥ x) ≈ (1-edge)/x`, capped at 1000×. Cash-out is adjudicated against server elapsed time under a lock. If a configured auto-cashout lies below the crash point, it is settled before a delayed UI tick can pass the crash boundary.
- **Limo:** select one of 2–5 cars; one is safe. Chance is `1/cars`; return multiplier is `cars × (1-edge)`.
- **Limbo:** a deterministic inverse-uniform result; win probability is approximately `1/target`. A win returns `bet × target × (1-edge)`.
- **Chicken Road:** five steps, three tiles, one safe per step. Each safe tile is digest-derived; multiplier is `3^steps × (1-edge)`. Cash out after a safe step; five steps settle automatically.
- **Pump:** buttons raise the multiplier in 0.25× steps. A hidden digest-derived burst point follows the Crash survival model, capped at 100×. A step that reaches or crosses it loses. Cash out is available at the current multiplier.

Interactive game inactivity timeouts settle as a loss according to the displayed rules. A process restart instead refunds every unsettled wager once; games do not resume because the UI state is not persisted. The refund is written to the ledger and linked fair-round record.

## Deploy from GitHub

The repository is arranged for source-based hosting: `bot.py`, `requirements.txt`, and the application packages are directly at the repository root. Connect the hosting service to this repository's `main` branch, use the repository root as the working directory, install with `python -m pip install -r requirements.txt`, and start with `python bot.py`. See [HOSTING.md](HOSTING.md) for required environment variables, persistent storage, and deposit safety. A `Procfile` is included for hosts that consume it; no `runtime.txt` is included because the provider is unspecified. Select Python 3.11 or newer in the host settings.

For a shell/VPS deployment, `sh run.sh` creates a virtual environment, installs dependencies, and starts the bot.

### Discord setup and permissions

Create an application and bot in the Discord Developer Portal. Invite with OAuth2 scopes `bot` and `applications.commands`. Grant the bot View Channels, Send Messages, Embed Links, Attach Files, and Read Message History in the game and audit channels. Enable the privileged Message Content intent in the Discord Developer Portal for prefix commands. Set the channel IDs for audit routes; the fairness route must be readable and sendable and players must be able to see its commitment and reveal posts. Use a test guild ID for immediate command sync while configuring the bot.

### Persistent storage and restart behavior

The default `DATABASE_URL=sqlite:///casino.db` stores the database relative to the process working directory. Many hosting panels discard this directory when containers are rebuilt. Use the provider's persistent volume path, for example `DATABASE_URL=sqlite:////absolute/provider/persistent/path/casino.db`; the parent directory is created at startup. Confirm with the provider that the chosen path survives rebuilds and is mounted writable. SQLite supports one bot process only; do not run replicas against one database.

Back up regularly with `python scripts/backup_db.py /secure/path/casino-backup.sqlite` and copy the backup off-host. A process restart refunds unsettled game wagers once; live game UI sessions do not resume. Keep the database private because it contains unrevealed fairness seeds. Local `logs/` files may be ephemeral; Discord log delivery is supplementary and not the financial ledger.

## Configuration

Copy `.env.example` to `.env` for local use, or set values in the hosting secret manager. Never commit `.env`, database files, private logs, or real credentials. Deployment-specific owner/admin IDs and channel IDs have no hardcoded defaults.

- **Discord:** `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `ADMIN_USER_IDS`, `OWNER_USER_IDS`, `ADMIN_CHANNEL_ID`. Sensitive admin commands require an allowlisted admin or owner; owners are required for rate and log routing changes. In guilds, the account must also have Discord Administrator permission.
- **Casino:** bets use whole virtual-credit units; `MIN_BET=1` is one VC and is not a dollar-denominated `$0.01` without a separate valuation policy. `MAX_BET=0` means no per-bet cap, while daily wager and payout caps still apply. Configure `MAX_PAYOUT`, `DAILY_BET_LIMIT`, `HOUSE_EDGE`, `MAINTENANCE_MODE`, branding/color, and optional image URLs. Runtime limits, edge, game availability, and log channel routes are persisted and audited in SQLite.
- **Required runtime values:** `DISCORD_TOKEN`, `OWNER_USER_IDS`, and a visible/sendable `FAIRNESS_LOG_CHANNEL_ID`; `ADMIN_USER_IDS` controls delegated administrators. `DISCORD_GUILD_ID` is optional but useful for test-guild command sync. `DATABASE_URL` should point to persistent storage on a host.
- **Database:** `DATABASE_URL=sqlite:///casino.db` by default. The adapter creates parent directories for a configured persistent path. It supports one SQLite process; PostgreSQL and multi-replica coordination are not implemented.
- **Fairness:** `FAIRNESS_ROTATION_SECONDS=1800`. Set `FAIRNESS_LOG_CHANNEL_ID` to a channel the bot can read and send messages in. Startup fails if it cannot publish the active commitment; fair rounds are blocked until commitments can be publicly announced. The route must be public enough for players to see commitments.
- **Apirone:** `APIRONE_ACCOUNT_ID`, `APIRONE_TRANSFER_KEY`, invoice lifetime, and polling interval. The bot uses private invoice polling, not callbacks. LTC is `ltc`, BNB Smart Chain USDT is `usdt@bnb`, and Ethereum USDT is `usdt@eth`; they are never interchangeable.
- **Conversion rates:** `VC_PER_LTC`, `VC_PER_USDT_BEP20`, `VC_PER_USDT_ERC20`, matching `VC_RATE_UPDATED_AT_*` Unix timestamps, `VC_RATE_SOURCE_*` labels, and `VC_RATE_MAX_AGE_SECONDS`. Rates default to zero and timestamps/sources are blank, so auto-credit remains off. Owners can set a rate, source, and timestamp with `/admin-rate`; the source should identify the reviewed exchange or policy. Stale, future-dated, or source-less rates hold a confirmed invoice for review.
- **Audit routes:** the eight `*_LOG_CHANNEL_ID` settings route withdrawals, wins, deposits, bets, admin actions, security, errors, and fairness. Discord delivery is supplementary; local rotated logs and SQLite ledgers are the durable records.
- **Withdrawals:** keep `WITHDRAWALS_ENABLED=false`; validation rejects enabling it. This project has no withdrawal request/execution provider, so the requested `$0.15` minimum and wager requirement cannot be enforced and are not configured.

### Deposit flow

`/deposit` uses Discord's asset choice selector and creates an invoice only after the Apirone response passes account, invoice ID, currency/network, amount, address format, initial status, and expiry checks. It shows the verified address, exact amount, selected network, expiry, Apirone invoice link (only for `https://apirone.com/invoice`), QR, a private copy-address button, and a private status-refresh button. `/deposit-status` is also available. A missing/partial credential pair disables the integration; provider errors never fall back to a generated address.

Amounts are converted to integer minor units with `Decimal`: LTC uses 8 decimals, USDT BEP20 uses 18, and USDT ERC20 uses 6 according to Apirone service metadata. Polling uses the authenticated private invoice endpoint and checks the exact account, invoice, asset/network, amount, stored destination, current status, and unique transaction history amounts. Only current `completed` status can credit; historical `partpaid` entries are valid transaction history when the current authenticated invoice is completed, and duplicate txids are counted once. The exact paid-unit total must equal the invoice. Expired uncredited invoices continue polling because Apirone documents that an already-sent transaction can complete after invoice expiry. Apirone's documented invoice callbacks have no signature fields, so they are not used. Credits also require a fresh traceable conversion rate and an atomic unique ledger reference. No live Apirone account was used; tests are mocked.

Current official Apirone docs: [Invoices](https://apirone.com/docs/invoices/), [Service info](https://apirone.com/docs/service/), and [Receiving callbacks](https://apirone.com/docs/callbacks/). Invoice docs list `created`, `paid`, `partpaid`, `overpaid`, `completed`, and `expired`; `completed` means required confirmations have been reached. Service info lists unit factors and minimum confirmations (LTC 1, USDT BEP20 4, USDT ERC20 64 in the current documentation). Invoice callbacks expose account, invoice, and status but no signature in the documented contract; callbacks are not accepted. A provider/adapter `failed` state is treated as terminal/no-credit, but `failed` is not in Apirone's documented invoice status list. Unknown statuses fail closed.

### Provably fair verification

The server seed is 32 random bytes encoded as hex. The bot publishes `SHA256(server_seed)` before associating that seed with a round. A round digest is `HMAC-SHA256(server_seed, "client_seed:nonce:game")`; the default client seed is the player’s Discord ID and the nonce is unique and increasing within a seed. Seeds rotate at the 30-minute age threshold. A retired seed is revealed only after all associated rounds settle or are safely refunded. Use `/fairness` for the active commitment and `/fair-verify <round_id>` after its seed is revealed.

Outcome derivations are versioned `casino-v1` and independently checked against the settled round record:

- Dice uses rejection-sampled HMAC-derived bounded integers.
- Mines ranks per-tile SHA-256 scores to select a unique mine layout.
- Dragon Tower and Limo use domain-separated HMAC digest derivations for safe paths and winning car.
- Blackjack uses a deterministic Fisher–Yates rank deck with digest-derived swaps and stores the dealt cards and final hands.
- Crash and Pump use the digest’s 52-bit uniform sample for inverse-CDF crash points.
- Limbo uses the digest’s 52-bit uniform sample for its inverse-uniform result.
- Chicken Road derives one deterministic safe tile per step.

The verifier checks commitments, HMAC digests, deterministic outcomes, selected paths/cards, and recorded payout parameters. A commitment log route is an external requirement; a missing route prevents a bot start or fair-round allocation rather than silently weakening the fairness claim. Protect the SQLite database because it contains seeds that have not yet been revealed.

## Commands

| Command | Purpose |
|---|---|
| `/casino`, `/help` | Lobby, rules, and help |
| `/balance`, `/transactions` | Wallet balance and ledger history |
| `/deposit`, `/deposit-history`, `/deposit-status` | Invoice creation, history, and authenticated status refresh |
| `/mines bet mines board` | Interactive Mines |
| `/blackjack bet` | Hit, stand, or double down |
| `/dragon-tower bet difficulty floors` | Climb the tower and cash out |
| `/crash bet auto_cashout` | Cash out manually or automatically |
| `/limo bet cars`, `/limbo bet target` | Pick game and multiplier game |
| `/dice bet direction target` | Under/over dice wager |
| `/chicken-road bet`, `/pump bet` | Step-based cash-out games |
| `/fairness`, `/fair-verify round_id` | Commitment and completed-round verification |
| `/play-limit`, `/play-status`, `/self-exclude` | Personal wager cap and timed self-exclusion |
| `/admin-config`, `/admin-status` | Private settings and diagnostics |
| `/admin-game`, `/admin-house-edge`, `/admin-limits`, `/admin-maintenance` | Audited game and wager controls |
| `/admin-rate`, `/admin-log-channel` | Owner-only conversion rate and log routes |
| `/admin-credit` | Audited wallet correction with a reason |
| `/admin-withdrawals` | Withdrawal kill switch; activation is refused |

## Operations, backups, troubleshooting

Use a process supervisor such as systemd and keep the data directory persistent. Example `ExecStart`:

```sh
/path/to/discord-casino-bot/.venv/bin/python /path/to/discord-casino-bot/bot.py
```

Back up with the bot stopped or use SQLite's online backup tool:

```sh
python scripts/backup_db.py /secure/path/casino-backup.sqlite
```

The bot applies additive migrations and records each version in `schema_migrations`. Restore by stopping the process, copying the current database aside, validating the backup, and then restoring it. Never point tests at the production database.

- Missing commands: confirm `applications.commands`, invite scopes, guild ID, and command sync.
- Missing fairness commitment: configure a readable/sendable fairness channel and verify the bot can publish there.
- Deposit held: check private invoice status, exact network, history totals, and whether the configured rate timestamp is within the freshness window and has a source.
- `database is locked`: run one process against a local persistent filesystem; do not use shared SQLite across replicas.
- Permission denied in an audit channel: correct the channel ID/permissions; gameplay does not treat Discord log delivery as a financial record.

## Testing and known limits

Run tests with temporary databases and simulated funds:

```sh
python -m pip check
python -m compileall -q bot.py cogs database games services tests
python -m pytest -q
```

Automated tests do not contact Discord or Apirone. No live Discord interaction rendering or live payment verification has been performed. There is no withdrawal provider, PostgreSQL support, external exchange-rate oracle, or resumable interactive UI after process restart. Keep deposits disabled until an operator has reviewed credentials, confirmation policy, conversion rate source and freshness, persistent storage, and jurisdiction requirements.


## Prefix commands (local upgrade)

See [PREFIX_COMMANDS.md](PREFIX_COMMANDS.md) for the complete dot-prefix reference, including the private player home, daily rewards, games, responsible-play controls, deposits, and admin commands. Discord Message Content Intent must be enabled in the Developer Portal.


Registered game, wallet, administration, and responsible-play slash commands are also exposed through the configured dot-prefix adapter. The prefix can be changed in the admin dashboard; see [PREFIX_COMMANDS.md](PREFIX_COMMANDS.md), [ADMIN_DASHBOARD_GUIDE.md](ADMIN_DASHBOARD_GUIDE.md), and [PHASE5_REPORT.md](PHASE5_REPORT.md).


New deposit invoice creation defaults to disabled; review `TERMUX_INSTALL.md` before changing `DEPOSITS_ENABLED`.


Phase 5 fixed bugs and new features are documented in [PHASE5_REPORT.md](PHASE5_REPORT.md). Admin settings are described in [ADMIN_DASHBOARD_GUIDE.md](ADMIN_DASHBOARD_GUIDE.md).


Download `discord-casino-bot-final-polished.zip` for the audited Phase 5 build. Follow [TERMUX_INSTALL.md](TERMUX_INSTALL.md) for installation and [ADMIN_DASHBOARD_GUIDE.md](ADMIN_DASHBOARD_GUIDE.md) for persistent settings.
