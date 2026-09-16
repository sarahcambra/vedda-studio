"""
Bukowskis fetcher. No official API (confirmed in research/auction-scanner.md
section 8) — server-rendered HTML, plain GET + regex extraction, no
headless browser needed. robots.txt checked 2026-09-16: /en/lots is not
disallowed (only /admin/, /cms/, /*/pdf are).

Read-only. Rate-limited — this is the biggest, most-watched auction house
on the list, be a reasonable citizen.

⚠️ Real search path is /en/lots?q=<term> — NOT /en/search, which 404s.
Confirmed live 2026-09-16.

Bukowskis also has something Auctionet doesn't: a real artist/designer
field on every listing (c-lot-index-lot__artist), not just free text in
the title.
"""

import re
import time
import html as html_lib
import urllib.request
import urllib.parse

import fetch_auctionet  # reuse seating filter + dedupe

BASE = "https://www.bukowskis.com/en/lots"
SLEEP_BETWEEN_CALLS = 2.0

CARD_SPLIT = re.compile(r'<a class="c-lot-index-lot__link[^"]*" href="([^"]+)"')
CATALOGUE_RE = re.compile(r'c-lot-index-lot__catalogue-number">([^<]*)<')
ARTIST_RE = re.compile(r'c-lot-index-lot__artist">([^<]*)<')
TITLE_RE = re.compile(r'c-lot-index-lot__title u-line-clamp">([^<]*)<')  # NOT c-lot-index-lot__title-block, that's the wrapper div and matches first
BID_RE = re.compile(r'c-lot-index-lot__result-value">([^<]*)<')
END_DATE_RE = re.compile(r'data-end-date="(\d+)"')
IMAGE_RE = re.compile(r'data-thumbnails="\[&quot;([^&]+)&')


def fetch_page(query):
    # ⚠️ the query param is "query", not "q" — the obvious guess was wrong,
    # found by reading the actual <form> on the page. Confirmed live 2026-09-16.
    url = f"{BASE}?{urllib.parse.urlencode({'query': query})}"
    req = urllib.request.Request(url, headers={"User-Agent": "Vedda Studio sourcing tool (internal use)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def parse_bid(text):
    """'2 450 SEK' -> 2450.0. Bukowskis uses a non-breaking/thin space
    as the thousands separator, not a comma."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return float(digits) if digits else None


def parse_cards(page_html):
    """Split the page on each lot card's opening link tag, then regex each
    chunk for its own fields — cards aren't otherwise cleanly delimited in
    the raw HTML without a real parser, and this avoids adding a dependency
    for a single-page scrape."""
    starts = [(m.start(), m.group(1)) for m in CARD_SPLIT.finditer(page_html)]
    cards = []
    for i, (pos, href) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(page_html)
        chunk = page_html[pos:end]
        cards.append((href, chunk))
    return cards


def normalise(href, chunk, source_query, kind):
    def find(rx):
        m = rx.search(chunk)
        return html_lib.unescape(m.group(1)).strip() if m else None

    lot_id = find(CATALOGUE_RE)
    artist = find(ARTIST_RE)
    title = find(TITLE_RE)
    end_ts = END_DATE_RE.search(chunk)

    return {
        "source": "bukowskis",
        "lot_id": lot_id or href,
        "url": href if href.startswith("http") else f"https://www.bukowskis.com{href}",
        "title": (f"{artist}. {title}" if artist and title else title) or "",
        "description": None,  # not on the listing card, only the full lot page — same tradeoff as Auctionet's location field
        "category": None,
        "current_bid": parse_bid(find(BID_RE)),
        "estimate_low": None,
        "estimate_high": None,
        "ends_at": int(end_ts.group(1)) if end_ts else None,  # unix timestamp, unlike Auctionet's ISO string — format_ends_at in run.py needs to handle both
        "image_url": find(IMAGE_RE),
        "has_image": bool(find(IMAGE_RE)),
        "artist": artist,  # real structured field Auctionet doesn't have — worth keeping even though db schema doesn't store it yet
        "matched_keyword": source_query,
        "matched_kind": kind,
    }


def is_excluded(title, exclude_terms):
    t = (title or "").lower()
    return any(term.lower() in t for term in exclude_terms)


def run(keywords_module):
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
            page_html = fetch_page(term)
            cards = parse_cards(page_html)
        except Exception as e:
            print(f"  ⚠️ Bukowskis fetch failed for '{term}': {e}")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue
        kept = 0
        for href, chunk in cards:
            lot = normalise(href, chunk, term, kind)
            if is_excluded(lot["title"], kw["exclude"]):
                continue
            if kw.get("seating_only") and not fetch_auctionet.is_seating(lot["title"], kw["seating_type_words"], kw["non_seating_type_words"]):
                continue
            results.append(lot)
            kept += 1
        print(f"  [bukowskis] '{term}': {len(cards)} results, {kept} kept after seating+exclude filter")
        time.sleep(SLEEP_BETWEEN_CALLS)

    deduped = fetch_auctionet.dedupe(results)
    print(f"  [bukowskis] {len(results)} raw -> {len(deduped)} unique after dedupe")
    return deduped


if __name__ == "__main__":
    print("Fetching Bukowskis (test: 'Lamino')...")
    page_html = fetch_page("Lamino")
    cards = parse_cards(page_html)
    print(f"{len(cards)} cards found.")
    for href, chunk in cards[:5]:
        lot = normalise(href, chunk, "Lamino", "model")
        print(" -", lot["title"], "|", lot["current_bid"], "kr |", lot["artist"])
