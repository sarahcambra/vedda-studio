#!/usr/bin/env python3
"""
Build dashboard.html from the JSON files in data/.

    python3 tools/build-dashboard.py

The dashboard is generated output. Never hand-edit dashboard.html — edit the
data files and re-run this. Visual language comes from site/styles.css (the
Vedda Studio design system, linked directly) — never hard-code a color, font
or spacing value the system's tokens already carry. See site/readme.md.
"""

import json
import os
import sqlite3
import datetime
import html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SCANNER_DB = os.path.join(ROOT, "tools", "scanner", "scanner.db")

STAGES = [
    ("sourced", "Sourced"),
    ("in_restoration", "In restoration"),
    ("ready", "Ready"),
    ("listed", "Listed"),
    ("sold", "Sold"),
]

# Piece/task status -> design-system tag class. tag-accent (Hunter Green) reads
# as "good/forward progress", tag-accent-2 (Cognac) as "in motion", tag-outline
# as neutral/default, tag-sold as the quiet done state, per site/readme.md.
STATUS_TAG = {
    "sourced": "tag-outline",
    "in_restoration": "tag-accent-2",
    "ready": "tag-accent",
    "listed": "tag-accent",
    "sold": "tag-sold",
    "todo": "tag-outline",
    "doing": "tag-accent-2",
    "blocked": "tag-outline note-critical",
    "done": "tag-sold",
}


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return json.load(fh)


def render(tpl, **kw):
    """Replace only the exact {key} tokens we pass.

    str.format() cannot be used here: the template carries CSS and JS, whose
    braces would all have to be escaped.
    """
    for k, v in kw.items():
        tpl = tpl.replace("{" + k + "}", str(v))
    return tpl


def money(v, dash="—"):
    if v is None:
        return dash
    return "{:,.0f} kr".format(v)


def pct(v, dash="—"):
    if v is None:
        return dash
    return "{:.0f}%".format(v * 100)


def kr_per_hour(v, dash="—"):
    if v is None:
        return dash
    return "{:,.0f} kr/hr".format(v)


def load_keywords():
    """Manual sourcing checklist reuses tools/scanner/keywords.json directly —
    one source of truth for search terms, not duplicated into data/."""
    path = os.path.join(ROOT, "tools", "scanner", "keywords.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_scan_results(limit=5000):
    """Reads tools/scanner/scanner.db directly — run python3 tools/scanner/run.py
    to refresh it, then rebuild the dashboard to pick up new results. Ordered
    bad-listing-score first (the actual edge, per research/auction-scanner.md
    section 5.4), most recently seen first within that. If scanner.db doesn't
    exist yet (scanner never run), returns an empty list rather than erroring —
    this section of the dashboard just shows nothing until it has data.
    limit is a safety cap, not a real page size — the archive should never
    get anywhere near it in normal use."""
    if not os.path.exists(SCANNER_DB):
        return [], 0, None
    conn = sqlite3.connect(SCANNER_DB)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
    last_scan = conn.execute("SELECT MAX(last_seen) FROM lots").fetchone()[0]
    rows = conn.execute(
        """SELECT * FROM lots
           ORDER BY bad_listing_score DESC, first_seen DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total, last_scan


def main():
    pc = load("pieces.json")
    tasks = load("tasks.json")
    kw = load_keywords()
    scan_lots, scan_total, scan_last_seen = load_scan_results()

    P = pc["pieces"]
    T = tasks["tasks"]

    sample = any(d.get("_sample") for d in (pc, tasks))

    # ---- derived figures -------------------------------------------------
    for p in P:
        p["_total_cost"] = (p["cost"] or 0) + (p["restoration_cost"] or 0)
        p["_projected_profit"] = (
            p["asking_price"] - p["_total_cost"]
            if p["asking_price"] is not None
            else None
        )
        if p["status"] == "sold" and p["sold_price"] is not None:
            p["_realised_profit"] = p["sold_price"] - p["_total_cost"]
        else:
            p["_realised_profit"] = None
        hrs = p.get("hours_actual") or 0
        if p["_realised_profit"] is not None and hrs:
            p["_kr_per_hour"] = p["_realised_profit"] / hrs
        else:
            p["_kr_per_hour"] = None

    held = [p for p in P if p["status"] != "sold"]
    capital_deployed = sum(p["_total_cost"] for p in held)
    projected = sum(p["_projected_profit"] or 0 for p in held)
    realised = sum(p["_realised_profit"] or 0 for p in P if p["_realised_profit"] is not None)
    rates = [p["_kr_per_hour"] for p in P if p["_kr_per_hour"] is not None]
    avg_rate = sum(rates) / len(rates) if rates else None

    today = datetime.date.today()

    def overdue(t):
        if not t["due"] or t["status"] == "done":
            return False
        try:
            return datetime.date.fromisoformat(t["due"]) < today
        except ValueError:
            return False

    open_tasks = [t for t in T if t["status"] != "done"]
    overdue_tasks = [t for t in open_tasks if overdue(t)]

    # ---- pipeline --------------------------------------------------------
    by_stage = {k: [p for p in P if p["status"] == k] for k, _ in STAGES}

    # ---- rate chart: kr/hour per realised piece ---------------------------
    rated = sorted([p for p in P if p["_kr_per_hour"] is not None], key=lambda x: -x["_kr_per_hour"])
    rate_max = max((p["_kr_per_hour"] for p in rated), default=1) or 1

    esc = html.escape

    def rate_band(v):
        if v is None:
            return ""
        if v > 500:
            return "rate-scale"
        if v >= 300:
            return "rate-adjust"
        return "rate-stop"

    # ---- render ----------------------------------------------------------
    def stat_block(label, value, sub="", note_cls="", value_cls=""):
        return (
            f'<div class="stat"><span class="kicker">{label}</span>'
            f'<div class="stat-value {value_cls}">{value}</div>'
            f'<div class="text-muted stat-sub {note_cls}">{sub}</div></div>'
        )

    # pipeline
    pipe_rows = []
    for i, (key, label) in enumerate(STAGES):
        items = by_stage[key]
        lines = "".join(
            '<li class="pline"><span class="pline-name">' + esc(p["name"]) + '</span>'
            + '<span class="pline-meta price">'
            + (money(p["asking_price"]) if p["asking_price"] else "price tbc")
            + "</span></li>"
            for p in items
        ) or '<li class="pline pline-empty">none</li>'
        pipe_rows.append(
            f'<div class="stage">'
            f'<div class="stage-head"><span class="label">{esc(label)}</span>'
            f'<span class="stage-count">{len(items)}</span></div>'
            f'<ul class="stage-list">{lines}</ul></div>'
        )

    # kr/hour bars
    rate_rows = []
    for p in rated:
        v = p["_kr_per_hour"]
        w = v / rate_max * 100.0
        rate_rows.append(
            f'<tr>'
            f'<th scope="row">{esc(p["name"])}</th>'
            f'<td class="barcell"><div class="bartrack">'
            f'<div class="bar {rate_band(v)}" style="--w:{w:.2f}%"></div></div></td>'
            f'<td class="num price">{kr_per_hour(v)}</td></tr>'
        )

    # inventory table
    inv_rows = []
    for p in P:
        tag_cls = STATUS_TAG.get(p["status"], "tag-outline")
        inv_rows.append(
            "<tr>"
            f'<td>{esc(p["name"])}</td>'
            f'<td>{esc(p.get("designer") or "—")}</td>'
            f'<td>{esc(p["era"] or "—")}</td>'
            f'<td>{esc(p.get("wood") or "—")}</td>'
            f'<td><span class="tag {tag_cls}">{esc(dict(STAGES)[p["status"]])}</span></td>'
            f'<td class="num price">{money(p["_total_cost"])}</td>'
            f'<td class="num price">{money(p["asking_price"])}</td>'
            "</tr>"
        )

    # tasks, overdue first then priority
    prio_rank = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(open_tasks, key=lambda t: (not overdue(t), prio_rank.get(t["priority"], 3)))
    task_rows = []
    for t in ordered:
        od = overdue(t)
        when = "overdue" if od else (t["due"] or "no date")
        when_cls = "note-critical" if od else "text-muted"
        tag_cls = STATUS_TAG.get(t["status"], "tag-outline")
        piece = ""
        if t.get("piece"):
            m = [p for p in P if p["id"] == t["piece"]]
            piece = m[0]["name"] if m else ""
        task_rows.append(
            f'<li class="task">'
            f'<div class="task-body"><div class="task-title">{esc(t["title"])}</div>'
            f'<div class="task-meta"><span class="tag {tag_cls}">{esc(t["status"])}</span>'
            f'<span class="{when_cls}">{esc(when)}</span>'
            + (f'<span class="text-muted">{esc(piece)}</span>' if piece else "")
            + "</div>"
            + (f'<div class="task-note text-muted">{esc(t["notes"])}</div>' if t.get("notes") else "")
            + "</div></li>"
        )

    # full table view
    piece_table = "".join(
        "<tr>"
        f'<th scope="row">{esc(p["name"])}</th>'
        f'<td>{esc(p["status"])}</td>'
        f'<td class="num price">{money(p["cost"])}</td>'
        f'<td class="num price">{money(p["restoration_cost"])}</td>'
        f'<td class="num price">{money(p["asking_price"])}</td>'
        f'<td class="num price">{money(p["sold_price"])}</td>'
        f'<td class="num price">{kr_per_hour(p["_kr_per_hour"])}</td>'
        "</tr>"
        for p in P
    )

    # ---- manual sourcing checklist (Facebook Marketplace etc — can't be automated) ---
    def dedupe_variants(terms):
        """Designers/models list carries spelling variants for the automated
        scanner (Ekström + Ekstrom, etc) — the manual checklist only needs
        one form per name, Facebook's own search is fuzzy enough."""
        seen_base = set()
        out = []
        for t in terms:
            base = t.lower().replace("-", " ").replace("ø", "o").replace("å", "a").replace("æ", "ae")
            base = "".join(c for c in base if c.isalnum() or c == " ")
            if base in seen_base:
                continue
            seen_base.add(base)
            out.append(t)
        return out

    CHECKLIST_GROUPS = [
        ("Designers", dedupe_variants(kw.get("designers", []))),
        ("Models", dedupe_variants(kw.get("models", []))),
        ("Woods", ["jakaranda", "palisander", "afrormosia", "valnöt", "alm", "teak"]),
        ("Lazy-listing (the alpha terms)", kw.get("lazy_listing_terms", [])),
        ("Styles & types", kw.get("no_designer_items", [])),
    ]
    checklist_total = sum(len(items) for _, items in CHECKLIST_GROUPS)

    def checklist_group_html(label, items):
        rows = "".join(
            f'<div class="chk-row">'
            f'<input type="checkbox" data-term="{esc(t)}">'
            f'<span class="chk-term" data-copy="{esc(t)}" title="Click to copy &amp; mark checked" tabindex="0" role="button">{esc(t)}</span>'
            f'</div>'
            for t in items
        )
        return f'<div class="chk-group"><h5>{esc(label)} <span class="text-muted">({len(items)})</span></h5><div class="chk-list">{rows}</div></div>'

    checklist_html = "".join(checklist_group_html(label, items) for label, items in CHECKLIST_GROUPS)

    # ---- scanner results — daily triage queue, love/discard state kept in the browser ---
    def format_scan_ends_at(value):
        if not value:
            return "—"
        try:
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            if isinstance(value, (int, float)):
                dt = datetime.datetime.fromtimestamp(value)
            else:
                dt = datetime.datetime.fromisoformat(value)
            return dt.strftime("%d %b")
        except (ValueError, OSError, TypeError):
            return "—"

    def parse_scan_ends_at(value):
        if not value:
            return None
        try:
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            if isinstance(value, (int, float)):
                return datetime.datetime.fromtimestamp(value)
            return datetime.datetime.fromisoformat(value)
        except (ValueError, OSError, TypeError):
            return None

    def scan_ends_badge(value):
        """(label, urgency_class) for the badge overlaid on the lot image.
        Matches the mockup's 'Ends 2h' / 'Ends 1d' style. urgency_class bands:
        urgent (<10h, cognac), '' beyond that (dark charcoal), ended (grey)."""
        dt = parse_scan_ends_at(value)
        if not dt:
            return "", ""
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        hours = (dt - datetime.datetime.now()).total_seconds() / 3600
        if hours < 0:
            return "Ended", "ended"
        if hours < 10:
            if hours < 1:
                mins = max(1, int(hours * 60))
                return f"Ends {mins}m", "urgent"
            return f"Ends {max(1, round(hours))}h", "urgent"
        days = round(hours / 24)
        return f"Ends {days}d", ""

    def hours_until_ends(value):
        """None if no end date (untimed listing, e.g. Haraldssons) or unparsable."""
        dt = parse_scan_ends_at(value)
        if not dt:
            return None
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return (dt - datetime.datetime.now()).total_seconds() / 3600

    def is_opportunity(lot):
        """'Underpriced' is defined directly: current bid at half the low
        estimate or less. Sarah's call (2026-09-21) — simpler and more
        literal than the composite bad-listing score. The flag only earns
        its 'worth reading first' urgency once there's actually a deadline
        forcing a decision — the final 48h before the auction ends (every
        newly-imported lot was showing it from day one otherwise, which made
        it meaningless noise). Listings with no end date at all (Haraldssons
        has none — fetch_haraldssons.py always sets ends_at=None) have no
        such window, so they flag from the moment they're imported instead."""
        bid = lot.get("current_bid")
        est_low = lot.get("estimate_low")
        if bid is None or not est_low:
            return False
        if bid > est_low * 0.5:
            return False
        hours_left = hours_until_ends(lot.get("ends_at"))
        return hours_left is None or hours_left <= 48

    SCAN_SRC_LABEL = {"auctionet": "Auctionet", "tradera": "Tradera", "bukowskis": "Bukowskis", "haraldssons": "Haraldssons", "siko": "Sikö"}
    MODEL_TERMS_LOWER = {t.lower() for t in kw.get("models", [])}
    DESIGNER_TERMS_LOWER = {t.lower() for t in kw.get("designers", [])}
    MODEL_DESIGNER_LOWER = {k.lower(): v for k, v in kw.get("model_designers", {}).items() if k != "_comment" and v}
    # BUY/MAYBE/NO sourcing signal per model, from model_database. PRESERVE and
    # PASS both fold into "NO" for the badge — a fast glance shouldn't need to
    # distinguish "don't touch, collector piece" from "don't touch, too
    # expensive"; the nuance lives in model_database.notes if she needs it.
    MODEL_STATUS_LOWER = {}
    for _e in kw.get("model_database", []):
        _m = (_e.get("model") or "").lower()
        _status = _e.get("vedda_status")
        if _m and _status:
            MODEL_STATUS_LOWER[_m] = "BUY" if _status == "BUY" else "MAYBE" if _status == "MAYBE" else "NO"

    def scan_ends_sort_key(value):
        if not value:
            return ""
        try:
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            if isinstance(value, (int, float)):
                return datetime.datetime.fromtimestamp(value).isoformat()
            return datetime.datetime.fromisoformat(value).isoformat()
        except (ValueError, OSError, TypeError):
            return ""

    def scan_card(lot):
        lot_key = esc(f"{lot['source']}-{lot['lot_id']}")
        is_flagged = is_opportunity(lot)
        img = (
            f'<img src="{esc(lot["image_url"])}" alt="" loading="lazy">'
            if lot.get("image_url")
            else f'<div class="scanimg-placeholder"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#C9C0A9" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"></rect><circle cx="9" cy="10" r="1.5"></circle><path d="M21 16l-5.5-5.5a2 2 0 00-2.8 0L4 19"></path></svg><span>{esc(lot.get("title") or "No image")}</span></div>'
        )
        src = lot.get("source") or ""
        location = lot.get("location")
        location_badge = f'<span class="scandot">·</span><span class="scanlocation"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#726752" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11z"></path><circle cx="12" cy="10" r="2.5"></circle></svg>{esc(location)}</span>' if location else ""

        # Ends badge
        ends_label, ends_class = scan_ends_badge(lot.get("ends_at"))
        ends_badge = ""
        if ends_label:
            ends_badge = (
                f'<span class="scanends-badge{" " + ends_class if ends_class else ""}" '
                f'title="ends {esc(format_scan_ends_at(lot.get("ends_at")))}">'
                f'<span class="scanends-dot"></span>'
                f'{esc(ends_label)}</span>'
            )

        # Tags — split the matched search terms into three kinds so a model
        # name and a designer surname never get buried inside the same
        # generic "teak chair" type tag. Sarah's call (2026-09-21): models
        # are the gold find (rare, name-searched collectible pieces) and
        # deserve their own badge; designer matches get a separate badge on
        # the side, not folded into the type tag either.
        tags_html = ""
        model_badge_html = ""
        designer_badge_html = ""
        matched = lot.get("matched_keyword") or ""
        terms = [t.strip() for t in matched.split(",") if t.strip()]
        type_terms = [t for t in terms if t.lower() not in MODEL_TERMS_LOWER and t.lower() not in DESIGNER_TERMS_LOWER]
        model_terms = [t for t in terms if t.lower() in MODEL_TERMS_LOWER]
        designer_terms = [t for t in terms if t.lower() in DESIGNER_TERMS_LOWER]
        if type_terms:
            tags_html = "".join(f'<span class="scantag">{esc(t)}</span>' for t in type_terms)
        if model_terms:
            status = MODEL_STATUS_LOWER.get(model_terms[0].lower())
            status_cls = f" scanbadge-model-{status.lower()}" if status else ""
            status_title = f' title="Sourcing status: {status}"' if status else ""
            model_badge_html = (
                f'<span class="scanbadge scanbadge-model{status_cls}"{status_title}>'
                '<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M12 2l2.9 6.3 6.9.9-5 4.9 1.2 6.9-6-3.3-6 3.3 1.2-6.9-5-4.9 6.9-.9z"></path></svg>'
                f'{esc(model_terms[0])}</span>'
            )
        designer_label = MODEL_DESIGNER_LOWER.get(model_terms[0].lower()) if model_terms else None
        if not designer_label and designer_terms:
            designer_label = designer_terms[0]
        if designer_label:
            designer_badge_html = f'<span class="scanbadge scanbadge-designer">{esc(designer_label)}</span>'

        # Banner for opportunity items — underpriced signal, not a risk warning
        banner_html = ""
        if is_flagged:
            banner_html = (
                f'<div class="scanbanner scanbanner-opportunity">'
                f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.9 6.3 6.9.9-5 4.9 1.2 6.9-6-3.3-6 3.3 1.2-6.9-5-4.9 6.9-.9z"></path></svg>'
                f'Likely underpriced — worth reading first'
                f'</div>'
            )

        # Bottom section: bid labels, values, bar, status, actions
        current_bid = lot.get("current_bid")
        est_low, est_high = lot.get("estimate_low"), lot.get("estimate_high")

        if current_bid is not None:
            bid_label = "Current bid"
            bid_value = money(current_bid)
        else:
            bid_label = "No bids yet"
            bid_value = "Opening only"

        if est_low is not None and est_high is not None:
            est_text = f"{money(est_low)}–{money(est_high)}"
        elif est_low is not None:
            est_text = money(est_low)
        elif est_high is not None:
            est_text = f"Up to {money(est_high)}"
        else:
            est_text = "None given"

        bar_html = ""
        status_html = ""
        if current_bid is not None and est_low is not None and est_high is not None and est_high > est_low:
            pct = max(0.0, min(1.0, (current_bid - est_low) / (est_high - est_low)))
            over = current_bid > est_high
            fill_color = "#C1573B" if over else "#4B7A5D"
            bar_html = (
                f'<div class="scanbar">'
                f'<div class="scanbar-fill" style="width:{pct * 100:.1f}%;background:{fill_color};"></div>'
                f'</div>'
            )
            if over:
                over_pct = (current_bid - est_high) / est_high * 100
                status_html = f'<div class="scanstatus" style="color:#C1573B;">{over_pct:.0f}% over high estimate</div>'
            else:
                status_html = f'<div class="scanstatus" style="color:#4B7A5D;">Within estimate</div>'
        elif current_bid is not None and est_low is not None:
            # Only a single estimate value — show simple bar against that value
            pct = max(0.0, min(1.0, current_bid / max(est_low, 1)))
            over = current_bid > est_low
            fill_color = "#C1573B" if over else "#4B7A5D"
            bar_html = (
                f'<div class="scanbar">'
                f'<div class="scanbar-fill" style="width:{pct * 100:.1f}%;background:{fill_color};"></div>'
                f'</div>'
            )
            if over:
                status_html = f'<div class="scanstatus" style="color:#C1573B;">Over estimate</div>'
            else:
                status_html = f'<div class="scanstatus" style="color:#4B7A5D;">Under estimate</div>'

        actions_html = (
            f'<a class="scanlink" href="{esc(lot.get("url") or "#")}" target="_blank">'
            f'View auction'
            f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3h7v7"></path><path d="M10 14L21 3"></path><path d="M21 14v6a1 1 0 01-1 1H4a1 1 0 01-1-1V4a1 1 0 011-1h6"></path></svg>'
            f'</a>'
            f'<div class="scanbtns">'
            f'<button class="scanicon scanbtn scanbtn-discard" data-action="discard" type="button" aria-label="Discard">'
            f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"></path></svg>'
            f'</button>'
            f'<button class="scanicon scanbtn scanbtn-love" data-action="love" type="button" aria-label="Love">'
            f'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20.5s-7.5-4.6-10-9.3C.5 7.8 2.3 4.5 5.7 4.5c2 0 3.4 1 6.3 4 2.9-3 4.3-4 6.3-4 3.4 0 5.2 3.3 3.7 6.7-2.5 4.7-10 9.3-10 9.3z"></path></svg>'
            f'</button>'
            f'<button class="scanbought scanbtn scanbtn-bought" data-action="bought" type="button">'
            f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"></path></svg>'
            f'Bought'
            f'</button>'
            f'</div>'
        )

        return (
            f'<div class="scancard" data-lot-key="{lot_key}" data-source="{esc(src)}" '
            f'data-flagged="{"1" if is_flagged else "0"}" '
            f'data-ends="{esc(scan_ends_sort_key(lot.get("ends_at")))}" '
            f'data-bid="{current_bid if current_bid is not None else ""}" '
            f'data-first-seen="{esc(str(lot.get("first_seen") or ""))}">'
            f'<div class="scanimgwrap">{img}{ends_badge}</div>'
            f'<div class="scanbody">'
            f'<div class="scantop"><span class="scansource">{esc(SCAN_SRC_LABEL.get(src, src))}</span>{location_badge}'
            f'<span class="scantop-side">{model_badge_html}{designer_badge_html}</span></div>'
            f'<a class="scantitle" href="{esc(lot.get("url") or "#")}" target="_blank">{esc(lot.get("title") or "")}</a>'
            f'<div class="scantags">{tags_html}</div>'
            f'{banner_html}'
            f'<div class="scan-bottom">'
            f'<div class="scanbid-labels"><span>{bid_label}</span><span>Estimate</span></div>'
            f'<div class="scanbid-values"><span class="scanbid-bid">{bid_value}</span><span class="scanbid-est">{est_text}</span></div>'
            f'{bar_html}{status_html}'
            f'<div class="scanactions">{actions_html}</div>'
            f'</div>'
            f'</div></div>'
        )

    scan_cards_html = "".join(scan_card(l) for l in scan_lots)
    scan_count = len(scan_lots)
    scan_flagged_count = sum(1 for l in scan_lots if is_opportunity(l))

    warn = (
        '<div class="warn"><strong>Sample data.</strong> '
        "These figures are placeholders that came with the setup. "
        "Replace <code>data/*.json</code> with real entries and delete the "
        "<code>_sample</code> flags.</div>"
        if sample
        else ""
    )

    def sourcing_stat(label, value, is_flagged=False):
        dot = '<span class="sourcing-stat-dot"></span>' if is_flagged else ''
        value_color = ' style="color:#C1573B;"' if is_flagged else ''
        return (
            f'<div class="sourcing-stat">'
            f'<div class="sourcing-stat-label">{dot}{label}</div>'
            f'<div class="sourcing-stat-value"{value_color}>{value}</div>'
            f'</div>'
        )

    sourcing_stats_html = "".join([
        sourcing_stat("Scanned", str(scan_total)),
        sourcing_stat("To triage", f'<span id="stat-triage">{scan_count}</span>'),
        sourcing_stat("Opportunities", str(scan_flagged_count), is_flagged=True),
        sourcing_stat("Loved", f'<span id="stat-loved">0</span>'),
    ])

    doc = render(
        TEMPLATE,
        warn=warn,
        generated=today.isoformat(),
        scan_last_seen_utc=esc((scan_last_seen or "").replace(" ", "T") + ("Z" if scan_last_seen else "")),
        sourcing_stats=sourcing_stats_html,
        stats="".join([
            stat_block("Capital deployed", money(capital_deployed),
                       f"across {len(held)} piece{'s' if len(held) != 1 else ''} held"),
            stat_block("In pipeline", str(len(held)), "not yet sold"),
            stat_block("Projected profit", money(projected), "if asking prices hold"),
            stat_block("Realised profit", money(realised), "on completed sales"),
            stat_block("Avg kr/hour", kr_per_hour(avg_rate), "across realised pieces",
                       "note-critical" if (avg_rate is not None and avg_rate < 300) else ""),
            stat_block("Open tasks", str(len(open_tasks)),
                       (f'{len(overdue_tasks)} overdue' if overdue_tasks else "none overdue"),
                       "note-critical" if overdue_tasks else ""),
        ]),
        pipeline="".join(pipe_rows),
        rate_rows="".join(rate_rows),
        inv_rows="".join(inv_rows),
        task_rows="".join(task_rows) or '<li class="task text-muted">Nothing outstanding.</li>',
        piece_table=piece_table,
        checklist_html=checklist_html,
        checklist_total=str(checklist_total),
        scan_cards_html=scan_cards_html or '<p class="text-muted">No scan results yet — run <code>python3 tools/scanner/run.py</code>, then rebuild the dashboard.</p>',
        scan_count=str(scan_count),
        scan_total=str(scan_total),
        scan_flagged_count=str(scan_flagged_count),
        piece_count=str(len(P)),
    )

    out = os.path.join(ROOT, "dashboard.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {out}")
    print(f"  pieces {len(P)} · tasks {len(T)} · scan lots {scan_total}")
    print(f"  capital deployed {money(capital_deployed)} · projected {money(projected)} · realised {money(realised)} · avg {kr_per_hour(avg_rate)}")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vedda Studio — business dashboard</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,400;0,500;0,600;1,400&amp;family=IBM+Plex+Sans:wght@400;500;600&amp;family=IBM+Plex+Mono:wght@400;500&amp;display=swap">
<link rel="stylesheet" href="site/styles.css">
<link rel="stylesheet" href="dashboard.css">
</head>
<body>
<div class="layout">
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-brand-row">
      <div class="sidebar-brand">Vedda Studio</div>
      <button class="sidebar-collapse" id="sidebar-collapse-btn" type="button" title="Collapse sidebar" aria-label="Collapse sidebar">‹</button>
    </div>
    <nav class="sidebar-nav" role="tablist">
      <button class="sidebar-item is-active" role="tab" aria-selected="true" data-tab="sourcing" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><path d="M21 21l-4.3-4.3"></path></svg>
        Sourcing
      </button>
      <button class="sidebar-item" role="tab" aria-selected="false" data-tab="inventory" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8l-9-5-9 5 9 5 9-5z"></path><path d="M3 8v8l9 5 9-5V8"></path><path d="M12 13v8"></path></svg>
        Inventory
      </button>
      <button class="sidebar-item" role="tab" aria-selected="false" data-tab="restorations" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 11-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 015.4-5.4z"></path></svg>
        Restorations
      </button>
      <button class="sidebar-item" role="tab" aria-selected="false" data-tab="business" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h9l3 3v15H6z"></path><path d="M9 8h6M9 12h6M9 16h4"></path></svg>
        Business
      </button>
      <div class="sidebar-divider"></div>
      <span class="sidebar-label">Catalogue</span>
      <a class="sidebar-item" href="docs/materials.html">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect></svg>
        Materials
      </a>
      <a class="sidebar-item" href="docs/suppliers.html">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="1"></rect><path d="M8 7V5a2 2 0 012-2h4a2 2 0 012 2v2"></path></svg>
        Suppliers
      </a>
      <a class="sidebar-item" href="docs/costings.html">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"></path></svg>
        Costings
      </a>
    </nav>
    <div class="sidebar-foot text-muted" id="sidebar-foot" data-last-scan="{scan_last_seen_utc}" data-scan-cron-hour-utc="6">
      generated {generated}
    </div>
  </aside>

  <main class="main">
  {warn}

  <div class="tabpanel" id="tab-sourcing" data-tab-panel="sourcing">
    <section class="section-block">
      <div class="sourcing-head">
        <div>
          <h1 class="sourcing-title">Today's pulls</h1>
          <div class="sourcing-sources">Auctionet · Tradera · Bukowskis · Haraldssons</div>
        </div>
        <div class="sourcing-stats">
          {sourcing_stats}
        </div>
      </div>
      <div class="scantoolbar">
        <div class="tabnav" id="scan-state-tabs" role="tablist"></div>
        <label class="scansort">
          <span class="scansort-label">Sort</span>
          <select id="scan-sort">
            <option value="ending">Ending soonest</option>
            <option value="bid">Highest bid</option>
            <option value="newest">Newest find</option>
          </select>
        </label>
      </div>
      <div class="tabnav" id="scan-source-tabs" role="tablist" style="margin-bottom:var(--space-6);"></div>
      <div class="scangrid" id="scan-grid">{scan_cards_html}</div>
      <div class="scanpager" id="scan-pager"></div>
    </section>

    <section class="section-block">
      <h4>Manual checklist — Facebook Marketplace</h4>
      <p class="text-muted">
        Can't be automated — Meta's ToS bans automated collection, with real enforcement history. Search these yourself, one at a time — click a term to copy it and mark it checked, then paste straight into Facebook's search box.
        Progress: <span id="chk-progress">0</span>/{checklist_total} checked. Saved in this browser only — checking from a different device or browser starts over.
        <button id="chk-reset" type="button" class="btn btn-secondary" style="margin-left:8px; padding:6px 14px;">Reset</button>
      </p>
      <div class="chk-grid">{checklist_html}</div>
    </section>
  </div>

  <div class="tabpanel" id="tab-inventory" data-tab-panel="inventory" hidden>
    <section class="section-block">
      <h4>Inventory</h4>
      <p class="text-muted">Coming soon — pieces you've bought, pulled from <code>data/pieces.json</code>.</p>
    </section>
  </div>

  <div class="tabpanel" id="tab-restorations" data-tab-panel="restorations" hidden>
    <section class="section-block">
      <h4>Restorations</h4>
      <p class="text-muted">Coming soon — a per-piece planner and tracker for pieces in restoration, built from <code>data/tasks.json</code>.</p>
    </section>
  </div>

  <div class="tabpanel" id="tab-business" data-tab-panel="business" hidden>
    <div class="statsrow">{stats}</div>
    <section class="section-block">
      <h4>Pipeline</h4>
      <p class="text-muted">Every piece sits in exactly one stage. Counts are pieces, not value.</p>
      <div class="pipeline">{pipeline}</div>
    </section>

    <section class="section-block">
      <h4>kr per hour of work</h4>
      <p class="text-muted">The success metric. &gt;500 scale it · 300–500 adjust · &lt;300 stop. Realised pieces only.</p>
      <div class="chart">
        <div class="legend">
          <span><i class="legend-swatch" style="background:var(--color-positive)"></i> &gt;500 scale</span>
          <span><i class="legend-swatch" style="background:var(--color-caution)"></i> 300–500 adjust</span>
          <span><i class="legend-swatch" style="background:var(--color-critical)"></i> &lt;300 stop</span>
        </div>
        <table>
          <tbody>{rate_rows}</tbody>
        </table>
        <details class="tableview">
          <summary>View as table</summary>
          <table class="table">
            <thead><tr><th>Piece</th><th>Stage</th><th class="num">Cost</th><th class="num">Restoration</th><th class="num">Asking</th><th class="num">Sold</th><th class="num">kr/hour</th></tr></thead>
            <tbody>{piece_table}</tbody>
          </table>
        </details>
      </div>
    </section>

    <section class="section-block">
      <h4>Piece ledger</h4>
      <p class="text-muted">{piece_count} pieces on file. Full financial detail — see the Inventory tab for the piece-level view.</p>
      <div class="tablewrap">
        <table class="table inv">
          <thead><tr><th>Piece</th><th>Designer</th><th>Era</th><th>Wood</th><th>Status</th><th style="text-align:right">Cost</th><th style="text-align:right">Asking</th></tr></thead>
          <tbody>{inv_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="section-block">
      <h4>Open tasks</h4>
      <p class="text-muted">Overdue first, then by priority.</p>
      <ul class="tasks">{task_rows}</ul>
    </section>
  </div>

  <footer>
    Generated by <code>tools/build-dashboard.py</code> from <code>data/*.json</code>.
    Edit the data, not this file.
  </footer>
  </main>
</div>

<script>
// tabs: click to switch, remember the last one open
(function () {
  var btns = document.querySelectorAll('.sidebar-item[data-tab]');
  var panels = document.querySelectorAll('[data-tab-panel]');
  function show(name) {
    if (!document.getElementById('tab-' + name)) return;
    btns.forEach(function (b) {
      var active = b.getAttribute('data-tab') === name;
      b.classList.toggle('is-active', active);
      b.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    panels.forEach(function (p) {
      p.hidden = p.getAttribute('data-tab-panel') !== name;
    });
    try { localStorage.setItem('vs-tab', name); } catch (e) {}
  }
  btns.forEach(function (b) {
    b.addEventListener('click', function () { show(b.getAttribute('data-tab')); });
  });
  var saved = null;
  try { saved = localStorage.getItem('vs-tab'); } catch (e) {}
  if (saved) show(saved);
})();

// sidebar collapse — per-browser convenience, same pattern as vs-tab
(function () {
  var sidebar = document.getElementById('sidebar');
  var btn = document.getElementById('sidebar-collapse-btn');
  if (!sidebar || !btn) return;
  function apply(collapsed) {
    sidebar.classList.toggle('is-collapsed', collapsed);
    btn.textContent = collapsed ? '›' : '‹';
    btn.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
  }
  var saved = null;
  try { saved = localStorage.getItem('vs-sidebar-collapsed'); } catch (e) {}
  apply(saved === '1');
  btn.addEventListener('click', function () {
    var next = !sidebar.classList.contains('is-collapsed');
    apply(next);
    try { localStorage.setItem('vs-sidebar-collapsed', next ? '1' : '0'); } catch (e) {}
  });
})();

// sidebar footer: real last-scan time (server-rendered) + next-scan time,
// computed client-side from the known daily UTC cron hour so it displays
// correctly in whichever timezone the viewer is actually in.
(function () {
  var el = document.getElementById('sidebar-foot');
  if (!el) return;
  var lastIso = el.getAttribute('data-last-scan');
  var cronHourUtc = parseInt(el.getAttribute('data-scan-cron-hour-utc'), 10);
  var lines = [];
  if (lastIso) {
    var last = new Date(lastIso);
    if (!isNaN(last)) lines.push('Last scan ' + last.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }));
  }
  if (!isNaN(cronHourUtc)) {
    var next = new Date();
    next.setUTCHours(cronHourUtc, 0, 0, 0);
    if (next <= new Date()) next.setUTCDate(next.getUTCDate() + 1);
    lines.push('Next scan ' + next.toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' }));
  }
  if (lines.length) el.innerHTML = lines.map(function (l) { return '<div>' + l + '</div>'; }).join('');
})();

// scan results: love/discard/bought state shared via Supabase — you and
// Amanda see the same clicks.
(function () {
  var cards = Array.prototype.slice.call(document.querySelectorAll('.scancard'));
  if (!cards.length) return;
  var pagerEl = document.getElementById('scan-pager');
  var sourceFilter = 'all';
  var stateFilter = 'all';
  var sortMode = 'ending';
  var PAGE_SIZE = 36;
  var currentPage = 1;
  var SOURCE_LABEL = { auctionet: 'Auctionet', tradera: 'Tradera', bukowskis: 'Bukowskis', haraldssons: 'Haraldssons' };
  var STATE_TAB_LABEL = { all: 'All', new: 'New', loved: 'Loved', discarded: 'Discarded', dealt_with: 'Dealt with' };

  var SUPABASE_URL = 'https://rnquevahynifwpyynrbd.supabase.co';
  var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJucXVldmFoeW5pZndweXlucmJkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk2MDQ5NDIsImV4cCI6MjEwNTE4MDk0Mn0.2xIZMYpxk-c6_xt7x8J0EkzRMWyRRRu4gy4kIEtLy1U';

  function sbHeaders() {
    return { 'apikey': SUPABASE_ANON_KEY, 'Authorization': 'Bearer ' + SUPABASE_ANON_KEY, 'Content-Type': 'application/json' };
  }

  function sbPatch(lotKey, fields) {
    return fetch(SUPABASE_URL + '/rest/v1/lots?lot_key=eq.' + encodeURIComponent(lotKey), {
      method: 'PATCH',
      headers: Object.assign(sbHeaders(), { 'Prefer': 'return=minimal' }),
      body: JSON.stringify(fields)
    }).catch(function (e) { console.warn('Supabase sync failed', e); });
  }

  function loadStates() {
    return fetch(SUPABASE_URL + '/rest/v1/lots?select=lot_key,state,discard_reason,bought_price,bought_date&state=neq.new', {
      headers: sbHeaders()
    }).then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; });
  }

  function renderSourceTabs() {
    var tabsEl = document.getElementById('scan-source-tabs');
    if (!tabsEl) return;
    var counts = { all: cards.length };
    cards.forEach(function (card) {
      var src = card.getAttribute('data-source') || '';
      counts[src] = (counts[src] || 0) + 1;
    });
    var sources = Object.keys(SOURCE_LABEL).filter(function (s) { return counts[s]; });
    var html = '<button class="tabbtn' + (sourceFilter === 'all' ? ' is-active' : '') + '" data-source-tab="all" type="button">All (' + counts.all + ')</button>';
    sources.forEach(function (s) {
      html += '<button class="tabbtn' + (sourceFilter === s ? ' is-active' : '') + '" data-source-tab="' + s + '" type="button">' + SOURCE_LABEL[s] + ' (' + counts[s] + ')</button>';
    });
    tabsEl.innerHTML = html;
    tabsEl.querySelectorAll('[data-source-tab]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        sourceFilter = btn.getAttribute('data-source-tab');
        currentPage = 1;
        applyFilters();
      });
    });
  }

  function cardStateBucket(card) {
    var state = card.getAttribute('data-state') || 'new';
    if (state === 'loved') return 'loved';
    if (state === 'bought') return 'dealt_with';
    if (state === 'discarded') return 'discarded';
    return 'new';
  }

  function renderStateTabs() {
    var tabsEl = document.getElementById('scan-state-tabs');
    if (!tabsEl) return;
    var counts = { all: 0, new: 0, loved: 0, discarded: 0, dealt_with: 0 };
    cards.forEach(function (card) {
      counts.all++;
      counts[cardStateBucket(card)]++;
    });
    var html = '';
    ['all', 'new', 'loved', 'discarded', 'dealt_with'].forEach(function (key) {
      var badge = '';
      if (key === 'dealt_with' && counts[key] > 0) {
        badge = ' <span class="tab-count">' + counts[key] + '</span>';
      }
      html += '<button class="tabbtn' + (stateFilter === key ? ' is-active' : '') + '" data-state-tab="' + key + '" type="button">' + STATE_TAB_LABEL[key] + badge + '</button>';
    });
    tabsEl.innerHTML = html;
    tabsEl.querySelectorAll('[data-state-tab]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        stateFilter = btn.getAttribute('data-state-tab');
        currentPage = 1;
        applyFilters();
      });
    });
    var lovedCountEl = document.getElementById('stat-loved');
    if (lovedCountEl) lovedCountEl.textContent = counts.loved;
    var triageCountEl = document.getElementById('stat-triage');
    if (triageCountEl) triageCountEl.textContent = counts.new;
  }

  function sortEligible(eligible) {
    var sorted = eligible.slice();
    if (sortMode === 'bid') {
      sorted.sort(function (a, b) {
        var av = parseFloat(a.getAttribute('data-bid')) || -1;
        var bv = parseFloat(b.getAttribute('data-bid')) || -1;
        return bv - av;
      });
    } else if (sortMode === 'newest') {
      sorted.sort(function (a, b) {
        return (b.getAttribute('data-first-seen') || '').localeCompare(a.getAttribute('data-first-seen') || '');
      });
    } else {
      sorted.sort(function (a, b) {
        var av = a.getAttribute('data-ends') || '9999';
        var bv = b.getAttribute('data-ends') || '9999';
        return av.localeCompare(bv);
      });
    }
    return sorted;
  }

  function applyFilters() {
    var eligible = [];
    cards.forEach(function (card) {
      var matchesSource = sourceFilter === 'all' || card.getAttribute('data-source') === sourceFilter;
      var matchesState = stateFilter === 'all' || cardStateBucket(card) === stateFilter;
      if (matchesSource && matchesState) {
        eligible.push(card);
      }
    });
    renderSourceTabs();
    renderStateTabs();

    eligible = sortEligible(eligible);

    var pageCount = Math.max(1, Math.ceil(eligible.length / PAGE_SIZE));
    if (currentPage > pageCount) currentPage = pageCount;
    var start = (currentPage - 1) * PAGE_SIZE;
    var end = start + PAGE_SIZE;

    cards.forEach(function (card) { card.hidden = true; });
    var gridEl = document.getElementById('scan-grid');
    eligible.slice(start, end).forEach(function (card) {
      card.hidden = false;
      if (gridEl) gridEl.appendChild(card);
    });

    renderPager(pageCount);
  }

  function renderPager(pageCount) {
    if (!pagerEl) return;
    if (pageCount <= 1) { pagerEl.innerHTML = ''; return; }
    var html = '';
    html += '<button type="button" class="btn btn-secondary scanpage-btn" data-page="' + (currentPage - 1) + '"' + (currentPage === 1 ? ' disabled' : '') + '>‹ Prev</button>';
    html += '<span class="scanpage-status">Page ' + currentPage + ' of ' + pageCount + '</span>';
    html += '<button type="button" class="btn btn-secondary scanpage-btn" data-page="' + (currentPage + 1) + '"' + (currentPage === pageCount ? ' disabled' : '') + '>Next ›</button>';
    pagerEl.innerHTML = html;
    pagerEl.querySelectorAll('.scanpage-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = parseInt(btn.getAttribute('data-page'), 10);
        if (!target || target < 1) return;
        currentPage = target;
        applyFilters();
        var gridEl = document.getElementById('scan-grid');
        if (gridEl) gridEl.scrollIntoView({ block: 'start', behavior: 'smooth' });
      });
    });
  }

  var STATE_MAP = { love: 'loved', bought: 'bought', discard: 'discarded' };
  var STATE_TAG_LABEL = { loved: 'LOVED', bought: 'BOUGHT' };

  function updateStateTag(card) {
    var state = card.getAttribute('data-state') || 'new';
    var top = card.querySelector('.scantop');
    if (!top) return;
    var existing = top.querySelector('.scan-state-tag');
    if (existing) existing.remove();
    var label = STATE_TAG_LABEL[state];
    if (label) {
      var tag = document.createElement('span');
      tag.className = 'tag tag-accent scan-state-tag';
      tag.textContent = label;
      top.appendChild(tag);
    }
  }

  cards.forEach(function (card) {
    var lotKey = card.getAttribute('data-lot-key');

    card.querySelectorAll('.scanbtn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.getAttribute('data-action'); // love / bought / discard
        var targetState = STATE_MAP[action];
        var current = card.getAttribute('data-state') || 'new';
        var next = current === targetState ? 'new' : targetState;

        var fields = { state: next };
        if (next === 'discarded') {
          var reason = window.prompt('Why discard this one? (optional — helps refine the buy filter later)', '');
          fields.discard_reason = reason || null;
        } else if (next === 'bought') {
          var price = window.prompt('Price paid (kr)?', '');
          var date = window.prompt('Purchase date (YYYY-MM-DD)?', new Date().toISOString().slice(0, 10));
          fields.bought_price = price ? parseFloat(price) : null;
          fields.bought_date = date || null;
        } else {
          fields.discard_reason = null;
        }

        card.setAttribute('data-state', next);
        updateStateTag(card);
        applyFilters();
        sbPatch(lotKey, fields);
      });
    });
  });

  var sortSelect = document.getElementById('scan-sort');
  if (sortSelect) {
    sortSelect.addEventListener('change', function () {
      sortMode = sortSelect.value;
      currentPage = 1;
      applyFilters();
    });
  }


  loadStates().then(function (rows) {
    var byKey = {};
    rows.forEach(function (r) { byKey[r.lot_key] = r; });
    cards.forEach(function (card) {
      var row = byKey[card.getAttribute('data-lot-key')];
      if (row && row.state) card.setAttribute('data-state', row.state);
      updateStateTag(card);
    });
    applyFilters();
  });

  applyFilters();
})();

// sourcing checklist: per-term checked state saved in this browser only
(function () {
  var boxes = document.querySelectorAll('.chk-row input[type="checkbox"]');
  var progressEl = document.getElementById('chk-progress');
  var resetBtn = document.getElementById('chk-reset');
  if (!boxes.length) return;

  function storeKey(term) { return 'vs-chk-' + term; }

  function updateProgress() {
    var checked = 0;
    boxes.forEach(function (b) { if (b.checked) checked++; });
    if (progressEl) progressEl.textContent = checked;
  }

  boxes.forEach(function (box) {
    var term = box.getAttribute('data-term');
    var row = box.closest('.chk-row');
    try {
      if (localStorage.getItem(storeKey(term)) === '1') {
        box.checked = true;
        row.classList.add('is-checked');
      }
    } catch (e) {}
    box.addEventListener('change', function () {
      row.classList.toggle('is-checked', box.checked);
      try { localStorage.setItem(storeKey(term), box.checked ? '1' : '0'); } catch (e) {}
      updateProgress();
    });
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', function () {
      boxes.forEach(function (box) {
        box.checked = false;
        box.closest('.chk-row').classList.remove('is-checked');
        try { localStorage.removeItem(storeKey(box.getAttribute('data-term'))); } catch (e) {}
      });
      updateProgress();
    });
  }

  // click the term itself: copy to clipboard, mark checked (you're about to search it)
  document.querySelectorAll('.chk-term').forEach(function (span) {
    function copyAndCheck() {
      var text = span.getAttribute('data-copy');
      var row = span.closest('.chk-row');
      var box = row.querySelector('input[type="checkbox"]');
      var finish = function () {
        span.classList.add('is-copied');
        setTimeout(function () { span.classList.remove('is-copied'); }, 700);
        if (box && !box.checked) {
          box.checked = true;
          row.classList.add('is-checked');
          try { localStorage.setItem(storeKey(box.getAttribute('data-term')), '1'); } catch (e) {}
          updateProgress();
        }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(finish).catch(finish);
      } else {
        finish();
      }
    }
    span.addEventListener('click', copyAndCheck);
    span.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); copyAndCheck(); }
    });
  });

  updateProgress();
})();

// material image carousels
(function () {
  document.querySelectorAll('[data-carousel]').forEach(function (car) {
    var slides = car.querySelectorAll('.carousel-slide');
    var dots = car.querySelectorAll('.carousel-dot');
    var i = 0;
    function go(n) {
      i = (n + slides.length) % slides.length;
      slides.forEach(function (s, idx) { s.classList.toggle('is-active', idx === i); });
      dots.forEach(function (d, idx) { d.classList.toggle('is-active', idx === i); });
    }
    var prev = car.querySelector('.carousel-prev'), next = car.querySelector('.carousel-next');
    if (prev) prev.addEventListener('click', function (e) { e.stopPropagation(); go(i - 1); });
    if (next) next.addEventListener('click', function (e) { e.stopPropagation(); go(i + 1); });
    dots.forEach(function (d) {
      d.addEventListener('click', function (e) {
        e.stopPropagation();
        go(parseInt(d.getAttribute('data-i'), 10));
      });
    });
  });
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
