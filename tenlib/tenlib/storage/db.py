# storage/db.py
import sqlite3
import os
from pathlib import Path


_DEFAULT_DB_PATH = Path.home() / ".tenlib" / "tenlib.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    source_lang TEXT,
    target_lang TEXT,
    mode        TEXT    NOT NULL DEFAULT 'translate',
    status      TEXT    NOT NULL DEFAULT 'in_progress',
    file_hash   TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL,
    chunk_index     INTEGER NOT NULL,
    original        TEXT    NOT NULL,
    translated      TEXT,
    token_estimated INTEGER,
    source_section  INTEGER,
    model_used      TEXT,
    confidence      REAL,
    status          TEXT    NOT NULL DEFAULT 'pending',
    flags           TEXT             DEFAULT '[]',
    FOREIGN KEY (book_id) REFERENCES books(id),
    UNIQUE (book_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS bible (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id      INTEGER NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    content_json TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    FOREIGN KEY (book_id) REFERENCES books(id)
);

CREATE TABLE IF NOT EXISTS quota_usage (
    model       TEXT    NOT NULL,
    date        TEXT    NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (model, date)
);
"""


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """
    Abre y configura la conexión a SQLite.
    Siempre devuelve rows como dicts (row_factory).
    Activa foreign keys — SQLite las tiene desactivadas por defecto.
    """
    path = db_path or os.environ.get("TENLIB_DB_PATH") or str(_DEFAULT_DB_PATH)

    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")   # mejor performance en lecturas concurrentes
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Crea las tablas si no existen. Idempotente."""
    with conn:
        conn.executescript(_SCHEMA)