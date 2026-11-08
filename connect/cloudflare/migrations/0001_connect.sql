-- Reservations count towards both limits, including expired and uncertain rows.
-- No automatic deletion: ownership and uncertain Cloudflare effects must survive.
CREATE TABLE computers (
    computer_id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    hpke_public_key TEXT NOT NULL UNIQUE,
    certificate_sha256 TEXT NOT NULL,
    hostname TEXT NOT NULL UNIQUE,
    origin_port INTEGER NOT NULL CHECK (origin_port BETWEEN 1 AND 65535),
    state TEXT NOT NULL CHECK (state IN ('reserved', 'claiming', 'ready', 'blocked', 'uncertain')),
    grant_hash TEXT UNIQUE CHECK (grant_hash IS NULL OR length(grant_hash) = 64),
    grant_expires_at INTEGER,
    operation_id TEXT UNIQUE,
    tunnel_id TEXT UNIQUE,
    dns_id TEXT UNIQUE,
    failure_code TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX computers_owner ON computers(owner_id);

-- SQLite serializes writers. These hard limits also protect direct SQL inserts.
CREATE TRIGGER computers_capacity BEFORE INSERT ON computers
WHEN NOT EXISTS (SELECT 1 FROM computers WHERE computer_id = NEW.computer_id)
BEGIN
    SELECT RAISE(ABORT, 'global_capacity') WHERE (SELECT count(*) FROM computers) >= 900;
    SELECT RAISE(ABORT, 'owner_capacity') WHERE
        (SELECT count(*) FROM computers WHERE owner_id = NEW.owner_id) >= 3;
END;

CREATE TRIGGER computers_identity BEFORE UPDATE ON computers
WHEN NEW.computer_id != OLD.computer_id OR NEW.owner_id != OLD.owner_id
    OR NEW.hpke_public_key != OLD.hpke_public_key OR NEW.hostname != OLD.hostname
    OR (OLD.tunnel_id IS NOT NULL AND NEW.tunnel_id IS NOT OLD.tunnel_id)
BEGIN
    SELECT RAISE(ABORT, 'immutable_identity');
END;

-- One durable account-wide mutation owner. It never expires automatically.
-- A crash or uncertain API reply requires operator reconciliation.
CREATE TABLE control_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    operation_id TEXT,
    acquired_at INTEGER
);
INSERT INTO control_lock(id) VALUES (1);
