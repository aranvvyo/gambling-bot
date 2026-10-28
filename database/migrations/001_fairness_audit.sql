-- Additive migration; safe on existing casino databases.
CREATE TABLE IF NOT EXISTS fair_seeds(id INTEGER PRIMARY KEY AUTOINCREMENT, commitment TEXT NOT NULL UNIQUE, server_seed TEXT NOT NULL, created_at INTEGER NOT NULL, retired_at INTEGER, revealed_at INTEGER);
CREATE TABLE IF NOT EXISTS fair_rounds(id TEXT PRIMARY KEY, seed_id INTEGER NOT NULL REFERENCES fair_seeds(id), discord_id INTEGER NOT NULL REFERENCES users(discord_id), game TEXT NOT NULL, client_seed TEXT NOT NULL, nonce INTEGER NOT NULL, result_digest TEXT NOT NULL, outcome TEXT, settled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, UNIQUE(seed_id,nonce));
CREATE INDEX IF NOT EXISTS ix_fair_seed_rounds ON fair_rounds(seed_id,settled);
CREATE TABLE IF NOT EXISTS app_config(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_by INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS admin_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TRIGGER IF NOT EXISTS transactions_no_update BEFORE UPDATE ON transactions BEGIN SELECT RAISE(ABORT,'financial ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS transactions_no_delete BEFORE DELETE ON transactions BEGIN SELECT RAISE(ABORT,'financial ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS admin_audit_no_update BEFORE UPDATE ON admin_audit BEGIN SELECT RAISE(ABORT,'admin audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS admin_audit_no_delete BEFORE DELETE ON admin_audit BEGIN SELECT RAISE(ABORT,'admin audit is append-only'); END;
