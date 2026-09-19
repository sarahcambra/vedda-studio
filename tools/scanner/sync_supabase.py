#!/usr/bin/env python3
"""
Pushes scanner.db rows into Supabase after each scan run.

scanner.db (local SQLite) stays the thing the scanner writes to directly —
that never depends on the internet being up mid-scan. This script is the
one-way sync from there to Supabase, which is what both dashboards actually
read from and what love/discard/bought state lives in.

Only overwrites the *scraped* columns (title, current_bid, ends_at, etc).
Never touches state, discard_reason, bought_price, bought_date,
delivery_price, delivery_price_estimated, notes — those are set from the
dashboard, by a person, and this script has no business clobbering them.

Needs SUPABASE_URL and SUPABASE_ANON_KEY set as env vars — never hardcoded,
never committed. Same pattern as TRADERA_APP_ID/TRADERA_APP_KEY.

    export SUPABASE_URL="https://xxxx.supabase.co"
    export SUPABASE_ANON_KEY="eyJ..."
    python3 tools/scanner/sync_supabase.py
"""
import datetime
import json
import os
import sqlite3
import urllib.request


def normalise_ends_at(value):
    """ends_at comes in as either an ISO string (Auctionet/Bukowskis) or a
    raw unix timestamp string/int (Tradera/Haraldssons) — Postgres'
    timestamptz column only accepts the former."""
    if not value:
        return None
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc).isoformat()
        except (ValueError, OSError):
            return None
    return value

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.db")
BATCH_SIZE = 200

SCRAPED_COLUMNS = [
    "source", "lot_id", "url", "title", "description", "category",
    "current_bid", "final_bid", "estimate_low", "estimate_high", "ends_at",
    "status", "bid_count", "location", "currency", "image_url",
    "matched_keyword", "matched_kind", "bad_listing_score", "price_score",
    "first_seen", "last_seen",
]


def load_rows():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT {', '.join(SCRAPED_COLUMNS)} FROM lots").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def to_supabase_row(row):
    out = {"lot_key": f'{row["source"]}-{row["lot_id"]}'}
    for col in SCRAPED_COLUMNS:
        out[col] = row[col]
    out["ends_at"] = normalise_ends_at(out["ends_at"])
    return out


def upsert_batch(base_url, anon_key, batch):
    url = f"{base_url}/rest/v1/lots?on_conflict=lot_key"
    body = json.dumps(batch).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Content-Type": "application/json",
        "User-Agent": "vedda-studio-scanner/1.0",
        # merge-duplicates: only the columns present in the payload get
        # overwritten (SCRAPED_COLUMNS) — state/discard_reason/etc are
        # simply absent from the payload, so PostgREST leaves them alone.
        "Prefer": "resolution=merge-duplicates,return=minimal",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def main():
    base_url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not base_url or not anon_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY not set.")
    base_url = base_url.rstrip("/")

    rows = [to_supabase_row(r) for r in load_rows()]
    print(f"Syncing {len(rows)} lots to Supabase...")

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        try:
            upsert_batch(base_url, anon_key, batch)
        except urllib.error.HTTPError as e:
            print(f"  ⚠️ batch {i}-{i+len(batch)} failed: {e.code} {e.read().decode('utf-8', 'ignore')[:300]}")
            continue
        print(f"  synced {i + len(batch)}/{len(rows)}")

    print("Done.")


if __name__ == "__main__":
    main()
