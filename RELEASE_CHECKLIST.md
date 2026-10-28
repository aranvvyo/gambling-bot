# Pre-publication checklist

## Hosting
- [ ] Extract the ZIP so `bot.py`, `requirements.txt`, and `.env.example` are at the configured working-directory root.
- [ ] Select Python 3.11 or newer; install with `python -m pip install -r requirements.txt` and launch with `python bot.py`.
- [ ] Confirm the provider's persistent mount path and set `DATABASE_URL` to that path.
- [ ] Configure the Discord bot token, owner/admin IDs, and visible/sendable fairness audit channel in secret environment settings.
- [ ] Confirm the host has only one active bot process and a restart policy.

## Before real users or deposits
- [ ] Obtain jurisdiction-specific legal review for age restrictions, gambling, payments, consumer protection, privacy, taxes, and sanctions.
- [ ] Have an independent reviewer validate game payout math, disclosed odds, fairness derivations, active commitment publication, seed reveal timing, and historical round verification.
- [ ] Verify Discord administrator allowlists, command and component permissions, and every audit channel permission.
- [ ] Keep `WITHDRAWALS_ENABLED=false`; no signed execution and reconciliation provider is implemented.
- [ ] Keep Apirone disabled until the account, exact asset/network handling, confirmations, invoice lifecycle, limits, and controlled end-to-end tests are approved.
- [ ] Use a reviewed rate source and timestamp for each asset. Defaults of zero prevent automatic conversion credit.
- [ ] Verify the database path survives host rebuilds. Test backup restore and restart refund behavior using a staging database.
- [ ] Configure private monitoring for process health, exceptions, deposit reconciliation, fairness publication, queue failures, and ledger reconciliation.
- [ ] Define retention/access policies for Discord IDs, payment metadata, local logs, and database backups.

## Verified in the release audit
- [ ] Dependency install from `requirements.txt`, `pip check`, compilation, cog loading, test suite, extracted archive smoke checks, and ZIP integrity.
- [ ] Mocked deposit/payment responses only; no live Apirone or Discord transaction was used.
