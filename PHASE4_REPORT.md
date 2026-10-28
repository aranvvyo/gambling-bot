# Phase 4 implementation and verification report

## Delivered

This archive adds a professional private deposit invoice card with provider-derived asset/network, exact amount/address, minimum, status and provider expiry where supplied. The QR is generated only from the actual Apirone address. The two-button row provides a raw-address-only ephemeral Copy Address response and an owner-checked Check Payment flow. The latter rechecks invoice ownership, queries Apirone, displays actual paid/remaining amounts when available, and delegates credit decisions to the existing verified, atomic, idempotent ledger path. Deposits remain disabled unless both configuration gates are enabled; this release has not live-verified Apirone.

A permission-checked `/admin-dashboard` (also available through the active prefix) provides persistent prefix preview/apply, maintenance preview/confirmation and notice, emoji mapping preview/edit/reset/remove/restore, log channel selection with send-permission validation and test embeds, deposit readiness and guarded activation, and casino name/accent branding. High-impact settings are audited. Maintenance blocks new wagers, extra wagers, tips, wallet adjustments, and invoice creation; ongoing games may settle so accepted wagers are not stranded.

The existing slash commands remain registered. The prefix adapter exposes registered commands using the dynamically resolved configured prefix. Help text, game menu examples, and prefix examples read the active prefix. Custom emoji mappings use the supplied IDs, check whether custom emoji are accessible to the bot, and fall back to Unicode. Settings are saved in the existing SQLite configuration table.

## Commands

- Wallet: `bal`, `balance`, `tip`, `transactions`, `profile`, `deposit-history`.
- Games: all registered games including `mines`, `blackjack`, `dragon-tower`, `crash`, `limbo`, `limo`, `dice`, `chicken-road`, and `pump`.
- Deposits: `depo`, `depoamount`, `deposit`, `deposit-status`, `deposit-history`. Only LTC, USDT BEP20, and USDT ERC20 are supported by the existing provider integration.
- Admin dashboard: `admin-dashboard`, `admin-prefix`, `admin-emoji`, `admin-logs`, `admin-deposits`, `admin-maintenance-panel`, `admin-branding`; existing admin commands are exposed by the prefix bridge and preserve their server-side checks.
- Responsible play and fairness: existing registered controls are available through the same prefix bridge.
- `help` and `games` show supported commands and menus.

The active default prefix is `.`. Prefix aliases are not enabled by default and work only if explicitly configured in the database.

## Tests and checks

- Baseline before Phase 4 changes: 164 passed.
- Final: `pytest -q` — 174 passed, 0 failed. There were 287 Python 3.14 / discord.py deprecation warnings (`asyncio.iscoroutinefunction`).
- The tests include mocked Apirone payment checks and idempotent ledger behavior; no real payments were sent and no live Discord or provider integration was tested.
- Missing `DISCORD_TOKEN` startup is tested to fail safely with exit code 2 and no traceback.
- Runtime QR generation, raw-only copy response, invoice ownership, inaccessible emoji fallback, persistence, maintenance checks, dashboard authorization, and rendered game result values have automated tests.

## Not live-verified / limitations

- Discord screenshots mentioned in the request were not available as readable files in this workspace, so the supplied design references could not be inspected here.
- No image-generation tool was available. The archive retains the existing bundled programmatic casino artwork and per-game outcome renderers. QR codes are produced dynamically from real invoice addresses, never from decorative assets.
- This release has no Coinflip game and does not add one. No withdrawal processor exists; withdrawals remain disabled.
- Live Apirone credentials, rates, provider behavior, Discord layout/thumbnail positioning, emoji availability in a target server, and channel permissions require local/server-side verification. Do not set `DEPOSITS_LIVE_VERIFIED=true` until those checks are complete.
