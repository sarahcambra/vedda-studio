"""
Haraldssons fetcher. Runs on Bidflow, a Nordic white-label auction SaaS —
confirmed 2026-09-16 by reading their JS bundle. robots.txt checked: only
/login?from= is disallowed, everything else (including this) is allowed.

Two-stage approach, not a full browser scrape of every page:

1. One Playwright page load of /auctions to read the list of active
   catalogue ids — this page is a client-rendered SPA shell with no data
   in the plain HTML, genuinely needs a browser once per run.
2. Real lot data comes from a plain JSON API (api/LotsApi/lots) that needs
   NO browser at all — confirmed callable directly with urllib. This is
   the part that runs ~14 times (once per catalogue) so keeping it
   browser-free matters for speed and reliability.

There is no keyword search on this site at all (confirmed — no search box
anywhere, browse-only by weekly catalogue). So this fetcher pulls EVERY
lot from every active catalogue and filters by keyword locally, the
opposite order from the other three fetchers.

Needs the playwright package + a Chromium binary — NOT a zero-dependency
script like the other three fetchers. Set up with:

    python3 -m venv tools/scanner/.venv
    source tools/scanner/.venv/bin/activate
    pip install playwright
    python3 -m playwright install chromium

Run this file with that venv's python, not the system one.
"""

import json
import re
import time
import urllib.request

import fetch_auctionet  # reuse seating filter + dedupe

AUCTIONS_PAGE = "https://haraldssonsauktioner.se/auctions"
LOTS_API = "https://haraldssonsauktioner.se/api/LotsApi/lots"
LOT_URL_TMPL = "https://haraldssonsauktioner.se/lot/{auction_slug}/{lot_id}"
IMAGE_URL_TMPL = "https://img.imageboss.me/byraneffecta/cover:contain/800x533/format:jpg/{image_id}"
SLEEP_BETWEEN_CALLS = 1.0


def get_active_catalogues():
    """The one Playwright step. Returns a list of (auction_id, slug) tuples,
    e.g. ('374', '374-mandag-2026-09-28')."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠️ Haraldssons skipped — playwright not installed in this Python. "
              "See the docstring at the top of fetch_haraldssons.py for setup.")
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(AUCTIONS_PAGE, timeout=30000)
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()

    slugs = re.findall(r'href="/catalogue/(\d+-[a-z0-9-]+)/EndingSoonest', html)
    return [(slug.split("-")[0], slug) for slug in dict.fromkeys(slugs)]  # dedupe, keep order


def fetch_lots_for_auction(auction_id, page=1, page_size=100):
    payload = [{
        "Payload": {"AuctionId": auction_id, "Language": "se", "BidAndEstimateSorting": "EndingSoonest", "Criteria": []},
        "Page": page, "PageSize": page_size, "SortBy": None,
    }]
    req = urllib.request.Request(
        LOTS_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Vedda Studio sourcing tool (internal use)"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body[0]["Total"], body[0]["Result"]


def normalise(raw, auction_slug, auction_name):
    lot_id = raw["LotId"]["LotId"].lstrip("+")
    title = (raw.get("Name") or {}).get("se") or ""
    images = raw.get("Images") or []
    image_url = IMAGE_URL_TMPL.format(image_id=images[0]["Id"]) if images else None
    return {
        "source": "haraldssons",
        "lot_id": lot_id,
        "url": LOT_URL_TMPL.format(auction_slug=auction_slug, lot_id=f"{lot_id}-item"),  # any slug suffix works — confirmed 2026-09-16 that a wrong one 301-redirects to the real canonical URL, only the numeric id matters
        "title": title,
        "description": None,  # not in this API response — only on the individual lot page
        "category": None,
        "current_bid": raw.get("CurrentBid"),
        "estimate_low": raw.get("Estimate") or None,
        "estimate_high": None,
        "ends_at": None,  # not in this endpoint — the catalogue's own date (in auction_name) is the closest proxy, see notes below
        "image_url": image_url,
        "has_image": bool(images),
        "matched_keyword": None,  # filled in during the local keyword match pass, not a per-request search term like the other sources
        "matched_kind": None,
        "_auction_name": auction_name,  # e.g. "Måndag 2026-09-28" — day of the auction, kept for reference since no exact end timestamp is available here
    }


def matches_any_keyword(title, terms):
    """⚠️ Word-boundary match, not plain substring. Found live 2026-09-16:
    the model 'Ari' (Arne Norell) was matching inside 'Karin' and
    'Safaristol' — any keyword short enough to be a substring of an
    unrelated word causes false positives here specifically, because this
    is local matching against raw text, unlike the other three fetchers
    which hand the term to the platform's own search engine and don't hit
    this problem the same way."""
    t = (title or "").lower()
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()) + r"\b"
        if re.search(pattern, t):
            return term
    return None


def run(keywords_module):
    kw = keywords_module
    all_terms = (
        kw["models"] + kw.get("designers", []) + kw["lazy_listing_terms"]
        + kw["no_designer_items"] + kw.get("woods", [])
    )

    catalogues = get_active_catalogues()
    if not catalogues:
        return []
    print(f"  [haraldssons] {len(catalogues)} active catalogues found")

    results = []
    for auction_id, slug in catalogues:
        try:
            total, lots = fetch_lots_for_auction(auction_id)
        except Exception as e:
            print(f"  ⚠️ Haraldssons fetch failed for catalogue {slug}: {e}")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue
        # paginate if this catalogue has more than one page of lots
        page = 2
        while len(lots) < total and page <= 5:  # hard cap, be reasonable
            _, more = fetch_lots_for_auction(auction_id, page=page)
            if not more:
                break
            lots += more
            page += 1
            time.sleep(SLEEP_BETWEEN_CALLS)

        auction_name = (lots[0].get("AuctionName") or {}).get("se") if lots else slug
        kept = 0
        for raw in lots:
            lot = normalise(raw, slug, auction_name)
            if fetch_auctionet.is_excluded(lot["title"], kw["exclude"]):
                continue
            matched = matches_any_keyword(lot["title"], all_terms)
            if not matched:
                continue
            if kw.get("seating_only") and not fetch_auctionet.is_seating(lot["title"], kw["seating_type_words"], kw["non_seating_type_words"]):
                continue
            lot["matched_keyword"] = matched
            lot["matched_kind"] = "model" if matched in kw["models"] else ("designer" if matched in kw.get("designers", []) else "other")
            results.append(lot)
            kept += 1
        print(f"  [haraldssons] {slug}: {total} total lots, {kept} matched a keyword")
        time.sleep(SLEEP_BETWEEN_CALLS)

    deduped = fetch_auctionet.dedupe(results)
    print(f"  [haraldssons] {len(results)} raw -> {len(deduped)} unique after dedupe")
    return deduped


if __name__ == "__main__":
    print("Fetching Haraldssons (all active catalogues, filtered locally)...")
    import fetch_auctionet as fa
    lots = run(fa.load_keywords())
    print(f"\n{len(lots)} lots matched.")
    for l in lots[:5]:
        print(" -", l["title"], "|", l["current_bid"], "kr |", l["matched_keyword"])
