"""
Auctionet fetcher. Undocumented JSON endpoint, country_code=SE, verified live
2026-09-16 (research/auction-scanner.md section 8). One Sweden-wide sweep per
keyword — covers Ekenbergs, Auktionskammaren Sydost and Växjö Auktionskammare
automatically since their lots sell through this same marketplace.

Read-only. Never bids. Rate-limited — this is an unsupported endpoint,
do not hammer it (section 2 of the research file).
"""

import json
import os
import time
import urllib.request
import urllib.parse

BASE = "https://auctionet.com/sv/search/16-mobler"  # furniture category only — cuts noise from unrelated categories (art, records, jewellery) drastically. Verified 2026-09-16: "Eva" unscoped returns mostly noise, scoped returns Bruno Mathsson Eva chairs top-ranked.
SLEEP_BETWEEN_CALLS = 2.0  # seconds — gentle on an undocumented endpoint


def load_keywords():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keywords.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fetch_one(query):
    params = {"q": query, "country_code": "SE", "format": "json"}
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Vedda Studio sourcing tool (internal use)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_excluded(title, exclude_terms):
    t = title.lower()
    return any(term.lower() in t for term in exclude_terms)


def is_seating(title, seating_words, non_seating_words):
    """Auctionet titles put the primary object type first, before the first
    comma — 'BYRÅ, 1900-talets mitt...' or 'BOKHYLLOR, ett par, teak...'.
    Check that segment first (it's the actual type, not a mention elsewhere
    in the description). Falls back to a whole-title scan if the leading
    segment doesn't clearly say either way — better to keep a maybe than
    silently drop something real."""
    t = title.lower()
    first_segment = t.split(",", 1)[0]
    has_seating_lead = any(w in first_segment for w in seating_words)
    has_non_seating_lead = any(w in first_segment for w in non_seating_words)
    if has_seating_lead:
        return True
    if has_non_seating_lead:
        return False
    # ambiguous leading segment — fall back to anywhere in the title
    return any(w in t for w in seating_words)


def normalise(raw_item, source_query, kind):
    # image_urls is a dict of {thumb, medium, full} for ONE image, not a list
    # of every photo in the listing — there's no true photo count in this
    # compact search response, only a per-item detail page would have that.
    image_urls = raw_item.get("image_urls") or {}
    return {
        "source": "auctionet",
        "lot_id": str(raw_item["id"]),
        "url": raw_item.get("url"),
        "title": raw_item.get("title"),
        "description": raw_item.get("description"),
        "category": raw_item.get("category"),
        "current_bid": raw_item.get("bid"),
        "estimate_low": raw_item.get("estimate"),
        "estimate_high": raw_item.get("upper_estimate"),
        "ends_at": raw_item.get("ends_at"),
        "image_url": image_urls.get("medium") or image_urls.get("full") or image_urls.get("thumb"),
        "has_image": bool(image_urls),
        "matched_keyword": source_query,
        "matched_kind": kind,
    }


def run(keywords=None):
    """Fetch every keyword list, normalise, drop excluded titles. Returns a list of lot dicts."""
    kw = load_keywords()
    all_terms = (
        [(t, "model") for t in kw["models"]]
        + [(t, "designer") for t in kw.get("designers", [])]
        + [(t, "lazy_listing") for t in kw["lazy_listing_terms"]]
        + [(t, "no_designer_item") for t in kw["no_designer_items"]]
        + [(t, "wood") for t in kw.get("woods", [])]
    )
    if keywords:
        all_terms = [(t, k) for t, k in all_terms if t in keywords]

    results = []
    for term, kind in all_terms:
        try:
            data = fetch_one(term)
        except Exception as e:
            print(f"  ⚠️ fetch failed for '{term}': {e}")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue
        items = data.get("items", [])
        kept = 0
        for raw in items:
            title = raw.get("title") or ""
            if is_excluded(title, kw["exclude"]):
                continue
            if kw.get("seating_only") and not is_seating(title, kw["seating_type_words"], kw["non_seating_type_words"]):
                continue
            results.append(normalise(raw, term, kind))
            kept += 1
        print(f"  '{term}': {len(items)} results, {kept} kept after seating+exclude filter")
        time.sleep(SLEEP_BETWEEN_CALLS)

    deduped = dedupe(results)
    print(f"\n{len(results)} raw results -> {len(deduped)} unique lots after dedupe "
          f"({len(results) - len(deduped)} were the same lot matched by more than one keyword)")
    return deduped


def dedupe(lots):
    """Same lot often matches several keywords (e.g. both 'Eva' and 'teak chair').
    Collapse to one row per (source, lot_id), keeping every keyword that matched
    it and preferring kind='model' if any of the matches was one — that's the
    kind the price/bad-listing scoring actually cares about."""
    by_id = {}
    for lot in lots:
        key = (lot["source"], lot["lot_id"])
        if key not in by_id:
            lot["matched_keywords"] = [lot["matched_keyword"]]
            by_id[key] = lot
            continue
        existing = by_id[key]
        existing["matched_keywords"].append(lot["matched_keyword"])
        if lot["matched_kind"] == "model" and existing["matched_kind"] != "model":
            existing["matched_kind"] = "model"
            existing["matched_keyword"] = lot["matched_keyword"]
    for lot in by_id.values():
        lot["matched_keyword"] = ", ".join(dict.fromkeys(lot["matched_keywords"]))
    return list(by_id.values())


if __name__ == "__main__":
    print("Fetching Auctionet, Sweden only...")
    lots = run()
    print(f"\n{len(lots)} lots fetched across all keywords (before dedupe).")
