# Prefix command reference

The default prefix is `.` and can be changed by an authorized administrator in the dashboard. Only explicitly stored aliases are accepted. Prefix commands use the same callbacks, wallet, fairness, payout rules, safety controls, and database as their slash equivalents. In guilds, account/game results that contain private information are sent by DM; the channel receives a short delivery notice.

Amounts without a coin unit are virtual credits (VC). The legacy `$` suffix is accepted as syntax only: `1$` means 1 VC and does not convert dollars to credits.

## Player home and account

- `{prefix}home` — private player home: balance, daily reward availability, recent ledger activity, latest deposit status, available games, and navigation buttons.
- `{prefix}bal` / `{prefix}balance` — wallet balance and today's wager total.
- `{prefix}profile` — account profile and available statistics.
- `{prefix}transactions` — private, paginated wallet ledger.
- `{prefix}limits` — casino limits and the user's personal cap/exclusion status.
- `{prefix}daily` — claim the configurable reward once every 24 hours. `DAILY_REWARD=0` disables claims. Claims use an atomic SQLite transaction and append-only ledger entry.
- `{prefix}leaderboard` — settled-round net results, calculated from game sessions and payout ledger rows. It does not show wallet balances or deposits.
- `{prefix}tip @user AMOUNT` — transfer VC to another human user; self-tips, bots, invalid amounts, and insufficient funds are rejected.

## Games

- `{prefix}games` — interactive directory, only showing enabled games.
- `{prefix}mines BET [MINES] [16|20]`
- `{prefix}blackjack BET`
- `{prefix}dragon-tower BET 2|3 [FLOORS]`
- `{prefix}crash BET [AUTO_CASHOUT]`
- `{prefix}limbo BET TARGET`
- `{prefix}limo BET [CARS]`
- `{prefix}dice BET over|under TARGET`
- `{prefix}chicken-road BET`
- `{prefix}pump BET`

All games keep their existing odds, provably-fair inputs, limits, and settlement logic. Game buttons are scoped to their owner and expire safely.

## Deposits

- `{prefix}depo` — send a private supported-network menu.
- `{prefix}depoamount ltc COIN_AMOUNT`, `{prefix}depoamount usdt@bnb COIN_AMOUNT`, or `{prefix}depoamount usdt@eth COIN_AMOUNT` — create an invoice only if live deposit gates are enabled, Apirone is configured, and the asset's sourced rate is fresh.
- `{prefix}deposit CURRENCY COIN_AMOUNT` — registered slash command through the prefix bridge.
- `{prefix}deposit-status INVOICE_ID` — privately refresh a deposit status with Apirone.
- `{prefix}deposit-history` — private, paginated invoice history.

Supported networks are Litecoin, USDT on BNB Smart Chain (BEP20), and USDT on Ethereum (ERC20). Real invoice creation remains off by default. Copy Address returns only the raw provider address privately. Check Payment verifies invoice ownership and the provider response; clicking never credits funds.

## Responsible play and fairness

- `{prefix}play-limit AMOUNT` — set a personal daily wager ceiling no higher than the casino cap.
- `{prefix}self-exclude DAYS` — start a confirmed 1–365 day exclusion. Repeating the command cannot shorten an active exclusion.
- `{prefix}play-status` — show current personal limits and exclusion status.
- `{prefix}fairness` and `{prefix}fair-verify ROUND_ID` — view commitments and verify a completed round.

## Administration

All admin functions validate authorization in the handler. Configured owners/admin IDs and server Administrators are accepted where appropriate; owner-only settings remain owner-only. A configured `ADMIN_CHANNEL_ID` restricts admin actions to that channel.

- `{prefix}admin-dashboard` / `{prefix}admin-config` — main configuration dashboard.
- `{prefix}admin-economy` — preview and update wager limits, daily reward, currency label, and per-game availability.
- `{prefix}admin-prefix` — preview and confirm the active prefix.
- `{prefix}admin-emoji` — configure supplied custom emoji mappings and fallbacks.
- `{prefix}admin-maintenance-panel` / `{prefix}admin-maintenance` — maintenance controls and notice.
- `{prefix}admin-logs` / `{prefix}admin-log-channel` — configure log destinations.
- `{prefix}admin-deposits` — deposit readiness, limits, and guarded activation.
- `{prefix}admin-branding` — casino name/accent color.
- `{prefix}admin-credit` and `{prefix}add @user AMOUNT` — audited wallet changes with server-side permission checks.
- `{prefix}admin-status`, `{prefix}admin-limits`, `{prefix}admin-game`, `{prefix}admin-house-edge`, `{prefix}admin-rate`, `{prefix}admin-withdrawals` — existing diagnostics and configuration controls. Real withdrawals are unavailable and locked off.

## Help

`{prefix}help` builds categories, syntax, aliases, and permission labels from the actually loaded prefix command registry. The slash command guide is `/help`.
