"""
Two scores per lot, per research/auction-scanner.md section 5.3/5.4.

price_score: rough expected profit if the model is recognised — NOT precise,
buyer's premium per house is still unresearched (open question in the file).
Use it to rank, not to decide alone.

bad_listing_score: the actual edge. High when the listing shows signs the
seller doesn't know what they have — that's where underpriced pieces hide.
"""

import json
import os

TARGET_HOURLY_RATE = 500  # kr, from CLAUDE.md
ASSUMED_BUYER_PREMIUM = 0.20  # 15-25% range, midpoint — real value is per-house, unresearched
ASSUMED_TRANSPORT = 500  # kr, midpoint of 200-800
ASSUMED_MATERIALS = 2000  # kr, midpoint of simple-job range
ASSUMED_RESTORATION_HOURS = 6  # rough midpoint across job types, unverified per itens.md


def load_model_prices():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_prices.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["models"]


def match_model(title, model_prices):
    """Fuzzy-ish: substring match, case-insensitive. Real fuzzy matching (Levenshtein)
    is a later upgrade — see research/auction-scanner.md section 5.5."""
    t = (title or "").lower()
    for model, spec in model_prices.items():
        if model.lower() in t:
            return model, spec
    return None, None


def price_score(lot, model_prices):
    """Returns (score, matched_model) or (None, None) if no model recognised."""
    model, spec = match_model(lot["title"], model_prices)
    if not model or spec.get("low") is None:
        return None, None
    expected_sale = spec["low"]  # conservative — low end of the normal-dealer range
    bid = lot.get("current_bid") or 0
    cost = bid * (1 + ASSUMED_BUYER_PREMIUM) + ASSUMED_TRANSPORT + ASSUMED_MATERIALS
    cost += ASSUMED_RESTORATION_HOURS * TARGET_HOURLY_RATE
    return expected_sale - cost, model


def bad_listing_score(lot, model_prices):
    """Higher = more likely underpriced because the seller doesn't know what they have.
    Weights are directional, not calibrated — tune once real outcomes come in."""
    score = 0
    title = (lot.get("title") or "")
    title_lower = title.lower()

    # Only meaningful when the lot was found via a model-name search — if we
    # searched a model term and the title itself doesn't repeat a recognised
    # model, that's a real signal. Applying this to lazy-listing/style
    # searches over-flagged almost everything in the first test run
    # (2026-09-16: 685/828 lots flagged, useless signal-to-noise).
    matched_model, _ = match_model(title, model_prices)
    if lot.get("matched_kind") == "model" and not matched_model:
        score += 1  # weak signal only — could be a fuzzy-match miss, not proof

    if any(dodsbo in title_lower for dodsbo in ["dödsbo", "flyttar", "måste bort"]):
        score += 2  # motivated seller, likely no research done

    if not lot.get("has_image"):
        score += 1.5  # no photo at all is a real signal; true photo COUNT isn't available from this endpoint (see fetch_auctionet.normalise)

    if lot.get("estimate_low") and lot.get("current_bid") is not None:
        if lot["current_bid"] < lot["estimate_low"] * 0.5:
            score += 2  # starting well below its own estimate

    dodsbo_terms = ["dödsbo", "flyttar", "måste bort"]
    if any(term in title_lower for term in dodsbo_terms):
        score += 1  # motivated seller, likely no research done

    return round(score, 1)


def score_lot(lot):
    model_prices = load_model_prices()
    p_score, model = price_score(lot, model_prices)
    b_score = bad_listing_score(lot, model_prices)
    lot["price_score"] = p_score
    lot["bad_listing_score"] = b_score
    lot["matched_model"] = model
    return lot
