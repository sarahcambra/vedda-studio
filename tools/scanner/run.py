#!/usr/bin/env python3
"""
Run the scanner: fetch -> normalise (done in fetch_*) -> score -> store -> report.

    python3 tools/scanner/run.py

Sources wired up: Auctionet, Tradera (needs TRADERA_APP_ID / TRADERA_APP_KEY
env vars — skips gracefully if unset, see fetch_tradera.py), Bukowskis,
Haraldssons, and Sikö (both need Playwright — skips gracefully if not
installed).
"""

import os
import re
import html
import datetime

import db
import score as scorer
import fetch_auctionet
import fetch_tradera
import fetch_bukowskis
import fetch_siko
import fetch_haraldssons

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    print("=== Vedda Studio auction scanner ===\n")

    print("Fetching Auctionet (Sweden only)...")
    lots = fetch_auctionet.run()
    print(f"\n{len(lots)} lots fetched from Auctionet, before dedupe.\n")

    print("Fetching Tradera...")
    tradera_lots = fetch_tradera.run(fetch_auctionet.load_keywords())
    print(f"{len(tradera_lots)} lots fetched from Tradera.\n")
    lots += tradera_lots

    print("Fetching Bukowskis...")
    bukowskis_lots = fetch_bukowskis.run(fetch_auctionet.load_keywords())
    print(f"{len(bukowskis_lots)} lots fetched from Bukowskis.\n")
    lots += bukowskis_lots

    print("Fetching Haraldssons...")
    haraldssons_lots = fetch_haraldssons.run(fetch_auctionet.load_keywords())
    print(f"{len(haraldssons_lots)} lots fetched from Haraldssons.\n")
    lots += haraldssons_lots

    print("Fetching Sikö...")
    siko_lots = fetch_siko.run(fetch_auctionet.load_keywords())
    print(f"{len(siko_lots)} lots fetched from Sikö.\n")
    lots += siko_lots

    print("Scoring...")
    scored = [scorer.score_lot(lot) for lot in lots]

    conn = db.connect()
    for lot in scored:
        db.upsert_lot(conn, lot)
    conn.commit()

    # Rank: bad-listing score first (the actual edge), then price score
    ranked = sorted(
        scored,
        key=lambda l: (l["bad_listing_score"] or 0, l["price_score"] or -999999),
        reverse=True,
    )

    out_path = os.path.join(ROOT, "report.html")
    write_report(ranked, out_path)
    conn.close()
    print(f"\nWrote {out_path}")
    print(f"Database: {db.DB_PATH}")


def money(v):
    if v is None:
        return "—"
    return f"{v:,.0f} kr"


def format_ends_at(value):
    """Auctionet/Tradera give an ISO string, Bukowskis gives a unix
    timestamp (int) — handle both rather than assume one shape."""
    if not value:
        return "—"
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            dt = datetime.datetime.fromtimestamp(int(value))
        else:
            dt = datetime.datetime.fromisoformat(value)
        return dt.strftime("%d %b, %H:%M")
    except (ValueError, OSError):
        return str(value)


def write_report(lots, out_path):
    esc = html.escape
    rows = []
    for l in lots:
        flag = "🚩" if (l["bad_listing_score"] or 0) >= 3 else ""
        desc = re.sub(r"<[^>]+>", " ", l.get("description") or "").strip()
        desc = re.sub(r"\s+", " ", desc)
        desc_short = (desc[:140] + "…") if len(desc) > 140 else desc
        img = (
            f'<img class="thumb" src="{esc(l["image_url"])}" alt="" loading="lazy">'
            if l.get("image_url")
            else '<div class="thumb thumb-empty"></div>'
        )
        source = l.get("source") or ""
        rows.append(
            "<tr>"
            f'<td>{flag}</td>'
            f'<td>{img}</td>'
            f'<td><span class="src src-{esc(source)}">{esc(source)}</span></td>'
            f'<td><a href="{esc(l["url"] or "#")}" target="_blank">{esc(l["title"] or "")}</a></td>'
            f'<td class="desc" title="{esc(desc)}">{esc(desc_short)}</td>'
            f'<td>{esc(l.get("matched_model") or "—")}</td>'
            f'<td class="num">{money(l["current_bid"])}</td>'
            f'<td class="num">{money(l["price_score"]) if l["price_score"] is not None else "—"}</td>'
            f'<td class="num">{l["bad_listing_score"]}</td>'
            f'<td>{format_ends_at(l.get("ends_at"))}</td>'
            f'<td>{esc(l.get("matched_keyword") or "")}</td>'
            "</tr>"
        )

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Auction scanner — report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f7f4ef; }}
  h1 {{ font-size: 20px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; }}
  th, td {{ padding: 6px 10px; border-bottom: 1px solid #e6e0d6; text-align: left; font-size: 13px; }}
  th {{ background: #f2ece2; text-transform: uppercase; font-size: 11px; letter-spacing: .04em; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.desc {{ max-width: 320px; color: #666; font-size: 12px; }}
  .thumb {{ width: 48px; height: 48px; object-fit: cover; border-radius: 4px; display: block; }}
  .thumb-empty {{ background: #e6e0d6; }}
  .src {{ display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 20px; text-transform: capitalize; }}
  .src-auctionet {{ background: #dbe8fb; color: #1c5cab; }}
  .src-tradera {{ background: #fde8d0; color: #a05a00; }}
  .src-bukowskis {{ background: #e0dcf5; color: #4c3a9e; }}
  .src-haraldssons {{ background: #d8f0e0; color: #1a7a45; }}
  .src-siko {{ background: #f5e0d8; color: #8a4518; }}
  tr:hover {{ background: #faf6f0; }}
</style>
</head>
<body>
<h1>Auction scanner — {len(lots)} lots, generated {datetime.date.today().isoformat()}</h1>
<p>🚩 = bad-listing score ≥ 3 (the pieces worth reading first). Price score is a rough estimate — buyer's premium per house is still unresearched, see research/auction-scanner.md open questions.</p>
<table>
<thead><tr><th></th><th>Photo</th><th>Source</th><th>Title</th><th>Description</th><th>Model matched</th><th>Current bid</th><th>Price score</th><th>Bad-listing score</th><th>Ends</th><th>Matched via</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)


if __name__ == "__main__":
    main()
