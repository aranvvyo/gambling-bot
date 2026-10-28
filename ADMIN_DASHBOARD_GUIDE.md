# Admin dashboard guide

Open `/admin-dashboard`, or use `{prefix}admin-dashboard` with the configured prefix. Dashboard controls are private, tied to the administrator who opened them, and expire after a short timeout. Each handler checks configured owner/admin IDs, server Administrator permission, and the optional `ADMIN_CHANNEL_ID`; button authorization is checked again.

## Categories

- **Overview:** online/maintenance state, uptime, active prefix, branding, deposits and withdrawal availability.
- **Prefix:** preview then confirm a 1–5 character safe prefix. Extra aliases are accepted only if explicitly stored in SQLite.
- **Maintenance:** view status, configure a notice, and explicitly confirm enable/disable. Wagers, tips, new deposits and wallet adjustments stop at database boundaries; already accepted games may settle normally.
- **Emoji mappings:** list mappings, preview changes, reset/remove a mapping, or restore all supplied defaults. Inaccessible server emojis fall back to Unicode.
- **Economy & games:** preview and confirm min/max wager, casino daily cap, max payout, daily reward, currency label, and individual game availability.
- **Log channels:** select a category and channel, validate bot send/embed permissions, save the route, and send a test embed. Wallet events fall back to the general route.
- **Deposit readiness:** credentials/rate freshness status, supported networks, limits, live-review flag, and guarded enable/disable. Withdrawal controls remain unavailable.
- **Branding:** preview and save the casino name and accent color.

All persistent settings use SQLite `app_config` and append-only admin audit records. Back up the database before upgrading. The dashboard cannot set `DEPOSITS_LIVE_VERIFIED`; this is a deliberate manual environment gate and must remain false until the live provider integration has been independently reviewed and safely tested.
