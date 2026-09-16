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


def load_scan_results(limit=2000):
    """Reads tools/scanner/scanner.db directly — run python3 tools/scanner/run.py
    to refresh it, then rebuild the dashboard to pick up new results. Ordered
    bad-listing-score first (the actual edge, per research/auction-scanner.md
    section 5.4), most recently seen first within that. If scanner.db doesn't
    exist yet (scanner never run), returns an empty list rather than erroring —
    this section of the dashboard just shows nothing until it has data.
    limit is a safety cap, not a real page size — the archive should never
    get anywhere near it in normal use."""
    if not os.path.exists(SCANNER_DB):
        return [], 0
    conn = sqlite3.connect(SCANNER_DB)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
    rows = conn.execute(
        """SELECT * FROM lots
           ORDER BY bad_listing_score DESC, first_seen DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def main():
    pc = load("pieces.json")
    sup = load("suppliers.json")
    tasks = load("tasks.json")
    mat = load("materials.json")
    pcost = load("piece_costings.json")
    kw = load_keywords()
    scan_lots, scan_total = load_scan_results()

    P = pc["pieces"]
    suppliers = {s["id"]: s for s in sup["suppliers"]}
    T = tasks["tasks"]
    M = mat["materials"]
    C = pcost["costings"]
    pieces_by_id = {p["id"]: p for p in P}

    sample = any(d.get("_sample") for d in (pc, sup, tasks, mat, pcost))

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
    def stat_block(label, value, sub="", note_cls=""):
        return (
            f'<div class="stat"><span class="kicker">{esc(label)}</span>'
            f'<div class="stat-value">{value}</div>'
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

    # ---- materials cards, grouped by category -----------------------------
    def fmt_material_price(m):
        if m["price"] is None:
            return "price tbc"
        sym = "€" if m.get("currency") == "EUR" else "kr"
        val = f"€{m['price']:,.0f}" if sym == "€" else f"{m['price']:,.0f} kr"
        out = f"{val} {esc(m['unit'])}"
        if m.get("price_ex_vat") is not None:
            ex = f"€{m['price_ex_vat']:,.0f}" if sym == "€" else f"{m['price_ex_vat']:,.0f} kr"
            out += f' <span class="text-muted">({ex} ex. VAT)</span>'
        return out

    CAT_LABEL = {"fabric": "Fabric", "interior": "Interior materials", "consumable": "Consumables", "equipment": "Equipment"}

    def material_card(m):
        supplier_name = ""
        if m.get("supplier"):
            s = suppliers.get(m["supplier"])
            supplier_name = s["name"] if s else m["supplier"]
        specs = []
        if m.get("martindale"):
            specs.append(f'{m["martindale"]:,} Martindale')
        if m.get("weight_gsm"):
            specs.append(f'{m["weight_gsm"]} g/m²')
        if m.get("width_cm"):
            specs.append(f'{m["width_cm"]} cm wide')
        specs_html = "".join(f'<span class="tag tag-outline">{esc(s)}</span>' for s in specs)
        images = m.get("images") or []
        if not images:
            img = '<div class="fig ar-square"></div>'
        elif len(images) == 1:
            img = f'<div class="fig ar-square"><img src="_assets/materials/{esc(images[0])}" alt=""></div>'
        else:
            slides = "".join(
                f'<img class="carousel-slide{" is-active" if i == 0 else ""}" '
                f'src="_assets/materials/{esc(src)}" alt="" data-i="{i}">'
                for i, src in enumerate(images)
            )
            dots = "".join(
                f'<button class="carousel-dot{" is-active" if i == 0 else ""}" data-i="{i}" '
                f'type="button" aria-label="Image {i+1}"></button>'
                for i in range(len(images))
            )
            img = (
                f'<div class="fig ar-square carousel" data-carousel>'
                f'{slides}'
                f'<button class="carousel-nav carousel-prev" type="button" aria-label="Previous image">‹</button>'
                f'<button class="carousel-nav carousel-next" type="button" aria-label="Next image">›</button>'
                f'<div class="carousel-dots">{dots}</div>'
                f'</div>'
            )
        subcat = f'<span class="tag tag-accent-2">{esc(m["subcategory"])}</span>' if m.get("subcategory") else ""
        note = f'<div class="text-muted matnote">{esc(m["price_note"])}</div>' if m.get("price_note") else ""
        link = f'<a class="btn-link" href="{esc(m["source_url"])}" target="_blank" rel="noopener">source</a>' if m.get("source_url") else ""
        return (
            '<div class="card matcard">'
            f'{img}'
            f'<div class="card-kicker">{esc(m["name"])}</div>'
            f'<div class="card-price price">{fmt_material_price(m)}</div>'
            f'<div class="tags-row">{subcat}{specs_html}</div>'
            f'<div class="text-muted">{esc(supplier_name)}</div>'
            f'{note}{link}'
            '</div>'
        )

    material_sections = []
    for cat in ("fabric", "interior", "consumable", "equipment"):
        items = [m for m in M if m["category"] == cat]
        if not items:
            continue
        cards = "".join(material_card(m) for m in items)
        priced = sum(1 for m in items if m["price"] is not None)
        material_sections.append(
            f'<div class="matcat">'
            f'<h4>{CAT_LABEL[cat]} <span class="text-muted">{priced}/{len(items)} priced</span></h4>'
            f'<div class="grid-pieces matgrid">{cards}</div></div>'
        )
    materials_html = "".join(material_sections) or '<p class="text-muted">No materials logged yet.</p>'

    supplier_cards = "".join(
        '<div class="supcard">'
        f'<div class="card-title-sm">{esc(s["name"])}</div>'
        f'<div class="text-muted">{esc(s.get("kind") or "")}{" · " + esc(s["trade"]) if s.get("trade") else ""}{" · " + esc(s["country"]) if s.get("country") else ""}</div>'
        + (f'<div class="suprating">{"★" * s["rating"]}{"☆" * (5 - s["rating"])}</div>' if s.get("rating") else "")
        + (f'<div class="supnotes">{esc(s["notes"])}</div>' if s.get("notes") else "")
        + '</div>'
        for s in sup["suppliers"]
    )

    # ---- piece costings -----------------------------------------------------
    MIN_MARKUP = 0.5
    PRICE_FLOOR = 6000
    materials_by_id = {m["id"]: m for m in M}

    def costing_card(c):
        p = pieces_by_id.get(c.get("piece"))
        piece_name = p["name"] if p else c.get("piece") or ""
        line_rows = "".join(
            "<tr>"
            f'<td>{esc(l["label"])}</td>'
            f'<td class="text-muted">{l["qty"]:g} {esc(l["unit"])}</td>'
            f'<td class="num price">{money(l["price_inc_vat"])}</td>'
            f'<td class="num price">{money(l["price_ex_vat"])}</td>'
            "</tr>"
            for l in c["lines"]
        )
        materials_ex = c["materials_ex_vat"]
        labour = c["labour_cost"]
        total_ex = c["total_cost_ex_vat"]
        total_inc = c["total_cost_inc_vat"]
        ask = c.get("asking_price")
        pair_ask = c.get("pair_asking_price")
        effective_ask = pair_ask if pair_ask is not None else ask
        markup = (effective_ask - total_ex) / total_ex if (effective_ask and total_ex) else None
        markup_ok = markup is not None and markup >= MIN_MARKUP
        floor_ok = effective_ask is not None and effective_ask >= PRICE_FLOOR
        rate = (effective_ask - total_ex) / c["labour_hours"] if (effective_ask and c.get("labour_hours")) else None

        checks = (
            f'<span class="{"note-positive" if markup_ok else "note-critical"}">'
            f'{"✓" if markup_ok else "✗"} {pct(markup) if markup is not None else "—"} markup (min 50%)</span>'
        )
        if ask is not None and ask < PRICE_FLOOR and pair_ask is None:
            checks += (
                f'<span class="{"note-positive" if floor_ok else "note-critical"}">'
                f'{"✓" if floor_ok else "✗"} {money(ask)} vs {money(PRICE_FLOOR)} price floor</span>'
            )

        img_html = ""
        for l in c["lines"]:
            mat_id = l.get("material")
            if mat_id:
                m = materials_by_id.get(mat_id)
                if m and m.get("images"):
                    img_html = f'<div class="fig ar-landscape"><img src="_assets/materials/{esc(m["images"][0])}" alt="{esc(m["name"])}"></div>'
                    break
        if not img_html:
            img_html = '<div class="fig ar-landscape"></div>'

        pair_span = f'<span class="text-muted">Pair: {money(pair_ask)}</span>' if pair_ask is not None else ""

        return (
            '<div class="card costcard">'
            f'{img_html}'
            f'<h4 class="card-title-sm">{esc(c.get("title") or piece_name)}</h4>'
            '<table class="table costtable">'
            '<thead><tr><th>Line</th><th>Qty</th><th class="num">Inc. VAT</th><th class="num">Ex. VAT</th></tr></thead>'
            f'<tbody>{line_rows}'
            f'<tr class="costsub"><td>Materials subtotal</td><td></td><td class="num price">{money(c["materials_inc_vat"])}</td><td class="num price">{money(materials_ex)}</td></tr>'
            f'<tr class="costsub"><td>Labour — {c["labour_hours"]:g}h @ {money(c["labour_rate"])}</td><td></td><td class="num price">{money(labour)}</td><td class="num price">{money(labour)}</td></tr>'
            f'<tr class="costtotal"><td>Total cost</td><td></td><td class="num price-lg">{money(total_inc)}</td><td class="num price-lg">{money(total_ex)}</td></tr>'
            '</tbody></table>'
            f'<div class="costmeta"><span class="price">Asking {money(ask)}</span>{pair_span}</div>'
            f'<div class="costchecks">{checks}</div>'
            + (f'<div class="text-muted matnote">{esc(c["notes"])}</div>' if c.get("notes") else "")
            + '</div>'
        )

    costing_html = "".join(costing_card(c) for c in C) or '<p class="text-muted">No costings logged yet.</p>'

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

    SCAN_SRC_LABEL = {"auctionet": "Auctionet", "tradera": "Tradera", "bukowskis": "Bukowskis", "haraldssons": "Haraldssons"}

    def scan_card(lot):
        lot_key = esc(f"{lot['source']}:{lot['lot_id']}")
        flag = '<span class="scanflag">🚩</span>' if (lot.get("bad_listing_score") or 0) >= 3 else ""
        img = (
            f'<img src="{esc(lot["image_url"])}" alt="" loading="lazy">'
            if lot.get("image_url")
            else ''
        )
        src = lot.get("source") or ""
        location = lot.get("location")
        location_badge = f'<span class="tag tag-accent-2">{esc(location)}</span>' if location else ""
        price_badge = (
            f'<span class="scanprice">{money(lot.get("current_bid"))}</span>'
            if lot.get("current_bid") is not None
            else '<span class="scanprice scanprice-empty">price tbc</span>'
        )
        return (
            f'<div class="scancard" data-lot-key="{lot_key}">'
            f'<div class="fig ar-landscape scanimgwrap">{img}{price_badge}</div>'
            '<div class="scanbody">'
            f'<div class="scantop"><span class="tag tag-outline">{esc(SCAN_SRC_LABEL.get(src, src))}</span>{flag}'
            f'{location_badge}'
            f'<span class="text-muted scanends">ends {esc(format_scan_ends_at(lot.get("ends_at")))}</span></div>'
            f'<a class="scantitle" href="{esc(lot.get("url") or "#")}" target="_blank">{esc(lot.get("title") or "")}</a>'
            f'<div class="text-muted scanmeta">matched "{esc(lot.get("matched_keyword") or "")}"</div>'
            '<div class="scanactions">'
            f'<button class="btn btn-secondary scanbtn scanbtn-love" data-action="love" type="button">♡ Love</button>'
            f'<button class="btn btn-secondary scanbtn scanbtn-discard" data-action="discard" type="button">✕ Discard</button>'
            '</div>'
            '</div></div>'
        )

    scan_cards_html = "".join(scan_card(l) for l in scan_lots)
    scan_count = len(scan_lots)

    warn = (
        '<div class="warn"><strong>Sample data.</strong> '
        "These figures are placeholders that came with the setup. "
        "Replace <code>data/*.json</code> with real entries and delete the "
        "<code>_sample</code> flags.</div>"
        if sample
        else ""
    )

    doc = render(
        TEMPLATE,
        warn=warn,
        generated=today.isoformat(),
        hero=money(capital_deployed),
        hero_sub=f"across {len(held)} piece{'s' if len(held) != 1 else ''} held",
        stats="".join([
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
        materials_html=materials_html,
        supplier_cards=supplier_cards or '<p class="text-muted">No suppliers logged yet.</p>',
        costing_html=costing_html,
        checklist_html=checklist_html,
        checklist_total=str(checklist_total),
        scan_cards_html=scan_cards_html or '<p class="text-muted">No scan results yet — run <code>python3 tools/scanner/run.py</code>, then rebuild the dashboard.</p>',
        scan_count=str(scan_count),
        scan_total=str(scan_total),
        supplier_count=str(len(suppliers)),
    )

    out = os.path.join(ROOT, "dashboard.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {out}")
    print(f"  pieces {len(P)} · suppliers {len(suppliers)} · tasks {len(T)} · materials {len(M)} · costings {len(C)}")
    print(f"  capital deployed {money(capital_deployed)} · projected {money(projected)} · realised {money(realised)} · avg {kr_per_hour(avg_rate)}")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vedda Studio — business dashboard</title>
<link rel="stylesheet" href="site/styles.css">
<link rel="stylesheet" href="dashboard.css">
</head>
<body>
<div class="page">
  <div class="nav">
    <span class="nav-brand">Vedda Studio</span>
    <span class="text-muted" style="margin-right:auto;">generated {generated}</span>
  </div>

  {warn}

  <div class="hero-block">
    <span class="kicker">Capital deployed</span>
    <div class="hero-value">{hero}</div>
    <div class="text-muted">{hero_sub}</div>
  </div>

  <div class="stats">{stats}</div>

  <div class="tabnav" role="tablist">
    <button class="tabbtn is-active" role="tab" aria-selected="true" data-tab="business" type="button">Business</button>
    <button class="tabbtn" role="tab" aria-selected="false" data-tab="suppliers" type="button">Suppliers &amp; Materials</button>
    <button class="tabbtn" role="tab" aria-selected="false" data-tab="sourcing" type="button">Sourcing</button>
  </div>
  <div class="hr hr-tight"></div>

  <div class="tabpanel" id="tab-business" data-tab-panel="business">
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
      <h4>Inventory</h4>
      <p class="text-muted">{supplier_count} suppliers on file.</p>
      <div class="tablewrap">
        <table class="table inv">
          <thead><tr><th>Piece</th><th>Designer</th><th>Era</th><th>Wood</th><th>Status</th><th style="text-align:right">Cost</th><th style="text-align:right">Asking</th></tr></thead>
          <tbody>{inv_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="section-block">
      <h4>Piece costing</h4>
      <p class="text-muted">Itemized bill of materials, inc. and ex. VAT, checked against the 50% markup rule and the 6,000 kr price floor.</p>
      <div class="costgrid">{costing_html}</div>
    </section>

    <section class="section-block">
      <h4>Open tasks</h4>
      <p class="text-muted">Overdue first, then by priority.</p>
      <ul class="tasks">{task_rows}</ul>
    </section>
  </div>

  <div class="tabpanel" id="tab-suppliers" data-tab-panel="suppliers" hidden>
    <section class="section-block">
      <h4>Materials</h4>
      <p class="text-muted">What you buy, grouped by what it's for. Prices as last checked — not live.</p>
      {materials_html}
    </section>

    <section class="section-block">
      <h4>Suppliers</h4>
      <p class="text-muted">Dealers, auction houses, restorers, textile and material suppliers.</p>
      <div class="supgrid">{supplier_cards}</div>
    </section>
  </div>

  <div class="tabpanel" id="tab-sourcing" data-tab-panel="sourcing" hidden>
    <section class="section-block">
      <h4>Scan results</h4>
      <p class="text-muted">
        Auctionet, Tradera, Bukowskis, Haraldssons — run once a day with <code>python3 tools/scanner/run.py</code>, then rebuild the dashboard to see fresh results here.
        <strong>{scan_total} lots archived</strong>, {scan_count} shown here, ranked by bad-listing score (🚩 = ≥3, worth reading first). New and loved shown; discarded is out of the way.
        Saved in this browser only.
        <a href="#" id="scan-show-discarded" class="btn-link scan-discarded-link"><span id="scan-link-label">Show discarded</span> (<span id="scan-discarded-count">0</span>)</a>
      </p>
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

  <footer>
    Generated by <code>tools/build-dashboard.py</code> from <code>data/*.json</code>.
    Edit the data, not this file.
  </footer>
</div>

<script>
// tabs: click to switch, remember the last one open
(function () {
  var btns = document.querySelectorAll('.tabbtn');
  var panels = document.querySelectorAll('[data-tab-panel]');
  function show(name) {
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

// scan results: love/discard state saved in this browser only.
// Default view: new + loved. Discarded is out of the way, not a toggle —
// just a small link to check the discard pile if you want to undo something.
(function () {
  var cards = Array.prototype.slice.call(document.querySelectorAll('.scancard'));
  if (!cards.length) return;
  var showDiscardedLink = document.getElementById('scan-show-discarded');
  var discardedCountEl = document.getElementById('scan-discarded-count');
  var pagerEl = document.getElementById('scan-pager');
  var discardedVisible = false;
  var PAGE_SIZE = 36;
  var currentPage = 1;

  function storeKey(lotKey) { return 'vs-scan-' + lotKey; }

  function applyFilters() {
    var discardedCount = 0;
    var eligible = [];
    cards.forEach(function (card) {
      var state = card.getAttribute('data-state') || 'new';
      if (state === 'discarded') {
        discardedCount++;
        if (discardedVisible) eligible.push(card);
      } else {
        eligible.push(card);
      }
    });
    if (discardedCountEl) discardedCountEl.textContent = discardedCount;

    var pageCount = Math.max(1, Math.ceil(eligible.length / PAGE_SIZE));
    if (currentPage > pageCount) currentPage = pageCount;
    var start = (currentPage - 1) * PAGE_SIZE;
    var end = start + PAGE_SIZE;

    cards.forEach(function (card) { card.hidden = true; });
    eligible.slice(start, end).forEach(function (card) { card.hidden = false; });

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

  cards.forEach(function (card) {
    var lotKey = card.getAttribute('data-lot-key');
    var saved = null;
    try { saved = localStorage.getItem(storeKey(lotKey)); } catch (e) {}
    if (saved) card.setAttribute('data-state', saved);

    card.querySelectorAll('.scanbtn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.getAttribute('data-action'); // 'love' or 'discard'
        var current = card.getAttribute('data-state') || 'new';
        var next = current === action + 'd' || current === action ? 'new' : (action === 'love' ? 'loved' : 'discarded');
        card.setAttribute('data-state', next);
        try {
          if (next === 'new') localStorage.removeItem(storeKey(lotKey));
          else localStorage.setItem(storeKey(lotKey), next);
        } catch (e) {}
        applyFilters();
      });
    });
  });

  var linkLabel = document.getElementById('scan-link-label');
  if (showDiscardedLink) {
    showDiscardedLink.addEventListener('click', function (e) {
      e.preventDefault();
      discardedVisible = !discardedVisible;
      if (linkLabel) linkLabel.textContent = discardedVisible ? 'Hide discarded' : 'Show discarded';
      currentPage = 1;
      applyFilters();
    });
  }

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
