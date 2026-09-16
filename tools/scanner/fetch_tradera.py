"""
Tradera fetcher. Official v3 SOAP-family API, PublicService.GetSearchResultAdvancedXml,
called via its plain HTTP GET variant — no SOAP envelope needed, no OAuth
token-login flow needed either. That flow (token-login / FetchToken /
RestrictedService) is only for actions on a specific seller's account
(listing, bidding, orders) — search lives under PublicService/SearchService,
which only needs the app-level appId + appKey. Confirmed live 2026-09-16.

Credentials: never hardcoded here. Set as environment variables:

    export TRADERA_APP_ID="..."
    export TRADERA_APP_KEY="..."

10,000 calls/24h per method on the free dev tier (per the account's own
method-limits page) — comfortably enough for this keyword list.
"""

import os
import re
import time
import html
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

import fetch_auctionet  # reuse the seating-type filter, keep the definition in one place

APP_ID = os.environ.get("TRADERA_APP_ID")
APP_KEY = os.environ.get("TRADERA_APP_KEY")

SEARCH_URL = "https://api.tradera.com/v3/publicservice.asmx/GetSearchResultAdvancedXml"
SLEEP_BETWEEN_CALLS = 1.0
NS = "{http://api.tradera.com}"  # response elements are unqualified once parsed via ET with this stripped, see parse_response


def credentials_present():
    return bool(APP_ID and APP_KEY)


def build_query_xml(search_words, items_per_page=48):
    # CategoryId 0 = all categories. Tradera has no furniture-only category
    # id confirmed yet — same "narrow this once we know the real id" note
    # as the Auctionet category scoping.
    words = html.escape(search_words)
    return (
        f"<Query><SearchWords>{words}</SearchWords><CategoryId>0</CategoryId>"
        f"<SearchInDescription>true</SearchInDescription>"
        f"<ItemsPerPage>{items_per_page}</ItemsPerPage></Query>"
    )


def fetch_one(query):
    if not credentials_present():
        raise RuntimeError("TRADERA_APP_ID / TRADERA_APP_KEY not set.")
    params = {
        "appId": APP_ID,
        "appKey": APP_KEY,
        "queryXml": build_query_xml(query),
    }
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Vedda Studio sourcing tool (internal use)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def strip_ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def parse_items(xml_text):
    """⚠️ Tradera's response has one <Items> element PER ITEM, not one
    wrapper containing every item — confirmed live 2026-09-16 (a "Lamino"
    search returning TotalNumberOfItems=7 produced 7 separate top-level
    <Items> elements, each with ~40 direct children — the item's own
    fields). Misreading this as a single wrapper was the first version's
    bug: it silently returned only 1 of 7 real matches with no error."""
    root = ET.fromstring(xml_text)
    items = []
    for items_el in root.iter():
        if strip_ns(items_el.tag) != "Items":
            continue
        current = {}
        for child in items_el:
            tag = strip_ns(child.tag)
            if list(child):
                continue  # nested block (ShippingOptions, ImageLinks, Seller, etc.) — skip, scalar fields only
            current[tag] = child.text
        if current.get("Id"):
            items.append(current)
    return items


def is_excluded(title, exclude_terms):
    t = (title or "").lower()
    return any(term.lower() in t for term in exclude_terms)


def normalise(raw, source_query, kind):
    return {
        "source": "tradera",
        "lot_id": raw.get("Id"),
        "url": raw.get("ItemLink"),
        "title": raw.get("ShortDescription"),
        "description": raw.get("LongDescription"),
        "category": raw.get("CategoryId"),
        "current_bid": float(raw["MaxBid"]) if raw.get("MaxBid") else None,
        "estimate_low": None,   # Tradera has no pre-sale estimate, unlike Auctionet
        "estimate_high": None,
        "ends_at": raw.get("EndDate"),
        "image_url": raw.get("ThumbnailLink"),
        "has_image": raw.get("Thumbnail") == "true",
        "matched_keyword": source_query,
        "matched_kind": kind,
    }


def run(keywords_module):
    if not credentials_present():
        print("  ⚠️ Tradera skipped — TRADERA_APP_ID / TRADERA_APP_KEY not set.")
        return []

    kw = keywords_module
    all_terms = (
        [(t, "model") for t in kw["models"]]
        + [(t, "designer") for t in kw.get("designers", [])]
        + [(t, "lazy_listing") for t in kw["lazy_listing_terms"]]
        + [(t, "no_designer_item") for t in kw["no_designer_items"]]
        + [(t, "wood") for t in kw.get("woods", [])]
    )

    results = []
    for term, kind in all_terms:
        try:
            xml_text = fetch_one(term)
            raw_items = parse_items(xml_text)
        except Exception as e:
            print(f"  ⚠️ Tradera fetch failed for '{term}': {e}")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue
        kept = 0
        for raw in raw_items:
            title = raw.get("ShortDescription") or ""
            if is_excluded(title, kw["exclude"]):
                continue
            if kw.get("seating_only") and not fetch_auctionet.is_seating(title, kw["seating_type_words"], kw["non_seating_type_words"]):
                continue
            results.append(normalise(raw, term, kind))
            kept += 1
        print(f"  [tradera] '{term}': {len(raw_items)} results, {kept} kept after seating+exclude filter")
        time.sleep(SLEEP_BETWEEN_CALLS)

    deduped = fetch_auctionet.dedupe(results)
    print(f"  [tradera] {len(results)} raw -> {len(deduped)} unique after dedupe")
    return deduped


if __name__ == "__main__":
    if not credentials_present():
        print("Set TRADERA_APP_ID and TRADERA_APP_KEY first.")
    else:
        print("Fetching Tradera (test: 'Lamino')...")
        xml_text = fetch_one("Lamino")
        items = parse_items(xml_text)
        print(f"{len(items)} items found.")
        for it in items[:3]:
            print(" -", it.get("ShortDescription"), "|", it.get("MaxBid"), "kr |", it.get("EndDate"))
