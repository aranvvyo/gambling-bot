CREATE TABLE IF NOT EXISTS users(discord_id INTEGER PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT, discord_id INTEGER NOT NULL REFERENCES users(discord_id), kind TEXT NOT NULL, amount INTEGER NOT NULL, balance_after INTEGER NOT NULL, reference TEXT UNIQUE, detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_transactions_user ON transactions(discord_id,id DESC);
CREATE TABLE IF NOT EXISTS deposits(invoice_id TEXT PRIMARY KEY, discord_id INTEGER NOT NULL REFERENCES users(discord_id), currency TEXT NOT NULL, requested_amount TEXT NOT NULL, address TEXT NOT NULL, status TEXT NOT NULL, txids TEXT NOT NULL DEFAULT '[]', credited INTEGER NOT NULL DEFAULT 0, verified_amount INTEGER NOT NULL DEFAULT 0, expires_at TEXT, invoice_url TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_deposits_user ON deposits(discord_id,created_at DESC);
CREATE TABLE IF NOT EXISTS game_sessions(id TEXT PRIMARY KEY, discord_id INTEGER NOT NULL REFERENCES users(discord_id), game TEXT NOT NULL, bet INTEGER NOT NULL CHECK(bet>0), state TEXT NOT NULL, settled INTEGER NOT NULL DEFAULT 0, session_max_payout INTEGER NOT NULL DEFAULT 1000000, session_max_bet INTEGER NOT NULL DEFAULT 10000, session_daily_limit INTEGER NOT NULL DEFAULT 50000, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS player_controls(discord_id INTEGER PRIMARY KEY REFERENCES users(discord_id), daily_limit INTEGER, excluded_until INTEGER);
CREATE TABLE IF NOT EXISTS fair_seeds(id INTEGER PRIMARY KEY AUTOINCREMENT, commitment TEXT NOT NULL UNIQUE, server_seed TEXT NOT NULL, created_at INTEGER NOT NULL, retired_at INTEGER, revealed_at INTEGER, revealed_published_at INTEGER);
CREATE TABLE IF NOT EXISTS fair_rounds(id TEXT PRIMARY KEY, seed_id INTEGER NOT NULL REFERENCES fair_seeds(id), discord_id INTEGER NOT NULL REFERENCES users(discord_id), game TEXT NOT NULL, client_seed TEXT NOT NULL, nonce INTEGER NOT NULL, result_digest TEXT NOT NULL, outcome TEXT, settled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, UNIQUE(seed_id,nonce));
CREATE INDEX IF NOT EXISTS ix_fair_seed_rounds ON fair_rounds(seed_id,settled);
CREATE TABLE IF NOT EXISTS app_config(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_by INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS admin_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TRIGGER IF NOT EXISTS transactions_no_update BEFORE UPDATE ON transactions BEGIN SELECT RAISE(ABORT,'financial ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS transactions_no_delete BEFORE DELETE ON transactions BEGIN SELECT RAISE(ABORT,'financial ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS admin_audit_no_update BEFORE UPDATE ON admin_audit BEGIN SELECT RAISE(ABORT,'admin audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS admin_audit_no_delete BEFORE DELETE ON admin_audit BEGIN SELECT RAISE(ABORT,'admin audit is append-only'); END;

CREATE TABLE IF NOT EXISTS daily_claims(discord_id INTEGER PRIMARY KEY REFERENCES users(discord_id), claimed_at INTEGER NOT NULL, amount INTEGER NOT NULL CHECK(amount>0));
