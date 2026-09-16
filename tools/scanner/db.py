"""
Scanner database. One sqlite file, every lot ever seen kept forever —
the accumulated price history is the actual long-term asset, not the alerts.
See research/auction-scanner.md section 6.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
    source TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    url TEXT,
    title TEXT,
    description TEXT,
    category TEXT,
    current_bid REAL,
    estimate_low REAL,
    estimate_high REAL,
    ends_at TEXT,
    image_url TEXT,
    matched_keyword TEXT,
    matched_kind TEXT,
    bad_listing_score REAL,
    price_score REAL,
    first_seen TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (source, lot_id)
);

CREATE INDEX IF NOT EXISTS idx_lots_ends_at ON lots(ends_at);
CREATE INDEX IF NOT EXISTS idx_lots_first_seen ON lots(first_seen);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_lot(conn, lot):
    """Insert a new lot, or update the live fields (bid, ends_at) on one already seen.
    first_seen never changes once set — that's the archive value."""
    existing = conn.execute(
        "SELECT lot_id FROM lots WHERE source = ? AND lot_id = ?",
        (lot["source"], lot["lot_id"]),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE lots SET current_bid = ?, ends_at = ?, last_seen = datetime('now')
               WHERE source = ? AND lot_id = ?""",
            (lot["current_bid"], lot["ends_at"], lot["source"], lot["lot_id"]),
        )
    else:
        conn.execute(
            """INSERT INTO lots
               (source, lot_id, url, title, description, category, current_bid,
                estimate_low, estimate_high, ends_at, image_url, matched_keyword,
                matched_kind, bad_listing_score, price_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lot["source"], lot["lot_id"], lot["url"], lot["title"],
                lot["description"], lot.get("category"), lot["current_bid"],
                lot.get("estimate_low"), lot.get("estimate_high"), lot["ends_at"],
                lot.get("image_url"), lot.get("matched_keyword"),
                lot.get("matched_kind"), lot.get("bad_listing_score"), lot.get("price_score"),
            ),
        )
