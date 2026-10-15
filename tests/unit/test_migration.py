"""init_db() upgrades a v2 database in place without losing rows."""

from sqlalchemy import create_engine, text

from src.shared.database import init_db

V2_SCHEMA = """
CREATE TABLE admin_users (id INTEGER NOT NULL, username VARCHAR(255) NOT NULL, password_hash VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, is_active BOOLEAN NOT NULL, PRIMARY KEY (id), UNIQUE (username));
CREATE TABLE odoo_connections (id INTEGER NOT NULL, name VARCHAR(255) NOT NULL, url VARCHAR(500) NOT NULL,
    "database" VARCHAR(255) NOT NULL, username VARCHAR(255) NOT NULL, credential TEXT NOT NULL,
    credential_type VARCHAR(20) NOT NULL, is_active BOOLEAN NOT NULL, status VARCHAR(20) NOT NULL,
    last_tested_at DATETIME, last_error TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, PRIMARY KEY (id));
CREATE TABLE api_keys (id INTEGER NOT NULL, name VARCHAR(255) NOT NULL, key_hash VARCHAR(255) NOT NULL,
    key_prefix VARCHAR(8) NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_used_at DATETIME, request_count INTEGER NOT NULL, PRIMARY KEY (id));
CREATE TABLE request_logs (id INTEGER NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    tool_name VARCHAR(100) NOT NULL, connection_id INTEGER, api_key_id INTEGER, status VARCHAR(20) NOT NULL,
    duration_ms INTEGER NOT NULL, error_message TEXT, PRIMARY KEY (id),
    FOREIGN KEY(connection_id) REFERENCES odoo_connections (id) ON DELETE SET NULL,
    FOREIGN KEY(api_key_id) REFERENCES api_keys (id) ON DELETE SET NULL);
CREATE INDEX ix_request_logs_timestamp ON request_logs (timestamp);
INSERT INTO odoo_connections (id, name, url, "database", username, credential, credential_type, is_active, status)
    VALUES (1, 'Arc De Sol', 'http://arcdesol-odoo:8069', 'arcdesol', 'admin', 'enc', 'password', 1, 'ok');
INSERT INTO api_keys (id, name, key_hash, key_prefix, is_active, request_count) VALUES (1, 'cc', 'h', 'abcd1234', 1, 49);
INSERT INTO request_logs (tool_name, connection_id, api_key_id, status, duration_ms) VALUES ('search_records', 1, 1, 'success', 30);
"""


def test_v2_database_is_migrated_in_place(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'v2.db'}")
    with engine.begin() as conn:
        for stmt in V2_SCHEMA.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))

    init_db(engine)
    init_db(engine)  # idempotent

    with engine.connect() as conn:
        c = conn.execute(text(
            "SELECT name, api_mode, verify_ssl, timeout, default_context, updated_at IS NOT NULL, credential_type "
            "FROM odoo_connections")).one()
        assert tuple(c) == ("Arc De Sol", "auto", 0, 120, None, 1, "password")
        k = conn.execute(text("SELECT name, scope, request_count FROM api_keys")).one()
        assert tuple(k) == ("cc", "write", 49)
        log = conn.execute(text("SELECT tool_name, response_bytes, transport FROM request_logs")).one()
        assert tuple(log) == ("search_records", None, None)
        indexes = {r[1] for r in conn.execute(text("PRAGMA index_list(api_keys)"))}
        assert "ix_api_keys_key_prefix" in indexes


def test_new_database_defaults(tmp_path):
    from sqlalchemy.orm import Session

    from src.shared.models import ApiKey, OdooConnection

    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    init_db(engine)
    with Session(engine) as db:
        db.add(OdooConnection(name="n", url="u", database="d", username="a", credential="c"))
        db.add(ApiKey(name="k", key_hash="h", key_prefix="p"))
        db.commit()
        conn = db.query(OdooConnection).one()
        assert (conn.api_mode, conn.verify_ssl, conn.timeout) == ("auto", True, 120)
        assert db.query(ApiKey).one().scope == "write"
