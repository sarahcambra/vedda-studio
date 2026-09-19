#!/usr/bin/env python3
"""
One-shot migration: data/materials.json + suppliers.json + piece_costings.json
→ Supabase (houses, suppliers, materials, material_offers, material_images,
costings, costing_lines). Idempotent — every write is an upsert on id, so it
can be re-run.

Needs the SERVICE ROLE key (the tables are authenticated-only; anon can't write).
Env only — never in a file, never in chat:

    SUPABASE_URL="https://xxxx.supabase.co" \
    SUPABASE_SERVICE_KEY="eyJ..." \
    python3 tools/migrate_to_supabase.py            # dry run: prints what it would write
    ... python3 tools/migrate_to_supabase.py --write # actually writes

What it does beyond a straight copy (all from research/):
  - splits fabric HOUSE (brand) from RETAILER: s-fabric-casamance becomes the
    retailer "chicandfabric.com"; houses Casamance / Coordonné / Güell Lamadrid /
    Manuel Canovas / William Morris & Co / Cathy Nordström / GP & J Baker created.
  - seeds the verified-live alternative offers from material-suppliers.md §4
    (that's the point of the many-to-many).
  - copies the 4 costings + their 31 lines VERBATIM as manual lines. Sarah's
    numbers are not recomputed here; the app has a Recalculate button for that.
  - uploads _assets/materials/*.jpg to the `materials` storage bucket.
"""
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITE = "--write" in sys.argv
BASE = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_KEY")
CHECKED = "2026-09-16"


def load(name):
    with open(os.path.join(ROOT, "data", name), encoding="utf-8") as fh:
        return json.load(fh)


def req(method, path, body=None, headers=None, raw=False):
    if not WRITE:
        return None
    # Cloudflare's bot protection 307-redirects Python's default urllib User-Agent
    # on POST/PATCH/DELETE (curl passes through fine, hence the earlier mystery).
    h = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "User-Agent": "vedda-studio-migration/1.0"}
    if body is not None and not raw:
        h["Content-Type"] = "application/json"
        body = json.dumps(body).encode("utf-8")
    h.update(headers or {})
    url = BASE + path
    try:
        # urllib refuses to follow 307/308 on non-GET (it would silently drop
        # the body) — Supabase's REST endpoint issues one on first contact,
        # so follow it ourselves, once, keeping method and body intact.
        for _ in range(2):
            r = urllib.request.Request(url, data=body, method=method, headers=h)
            try:
                with urllib.request.urlopen(r, timeout=60) as resp:
                    txt = resp.read().decode("utf-8")
                    return json.loads(txt) if txt else None
            except urllib.error.HTTPError as e:
                if e.code in (307, 308) and e.headers.get("Location"):
                    url = e.headers["Location"]
                    continue
                raise
    except urllib.error.HTTPError as e:
        print(f"  ✗ {method} {path}: {e.code} {e.read().decode('utf-8', 'ignore')[:400]}")
        raise


def normalise_keys(rows):
    all_keys = set()
    for r in rows:
        all_keys.update(r.keys())
    return [{k: r.get(k) for k in all_keys} for r in rows]


def upsert(table, rows, on_conflict="id"):
    if not rows:
        return
    print(f"  {table}: {len(rows)} rows")
    if not WRITE:
        for r in rows[:3]:
            print("    ", json.dumps(r, ensure_ascii=False)[:160])
        if len(rows) > 3:
            print("     …")
        return
    # PostgREST's bulk insert requires every object to have the same keys —
    # our row dicts vary (not every house has notes, not every offer has a
    # width override, etc). Union the keys, fill the gaps with null.
    req("POST", f"/rest/v1/{table}?on_conflict={on_conflict}", normalise_keys(rows),
        {"Prefer": "resolution=merge-duplicates,return=minimal"})


def upload_image(local_path, storage_path):
    if not WRITE:
        return
    ctype = mimetypes.guess_type(local_path)[0] or "image/jpeg"
    with open(local_path, "rb") as fh:
        data = fh.read()
    req("POST", f"/storage/v1/object/materials/{storage_path}", data,
        {"Content-Type": ctype, "x-upsert": "true"}, raw=True)


# ----------------------------------------------------------------- houses
HOUSES = [
    {"id": "h-casamance", "name": "Casamance", "country": "France", "website": "https://www.casamance.com"},
    {"id": "h-coordonne", "name": "Coordonné", "country": "Spain", "website": "https://www.coordonne.es"},
    {"id": "h-guell-lamadrid", "name": "Güell Lamadrid", "country": "Spain", "website": "https://www.guell-lamadrid.com"},
    {"id": "h-manuel-canovas", "name": "Manuel Canovas", "country": "France", "website": "https://www.manuelcanovas.com",
     "notes": "Distributed via Colefax & Fowler (trade@colefax.com). Retailers sometimes file it under Colefax — check the vendor tag."},
    {"id": "h-william-morris", "name": "William Morris & Co", "country": "UK", "website": "https://www.williammorris.co.uk"},
    {"id": "h-cathy-nordstrom", "name": "Cathy Nordström", "country": "Sweden", "website": "https://www.cathynordstrom.com",
     "notes": "Sells direct — also a supplier row (s-fabric-cathynordstrom). 20,000 Martindale on the linens: light domestic."},
    {"id": "h-gp-j-baker", "name": "GP & J Baker", "country": "UK", "website": "https://www.gpjbaker.com"},
    {"id": "h-gabriel", "name": "Gabriel", "country": "Denmark", "website": "https://www.gabriel.dk"},
]

# supplier id → house id (for houses that sell direct)
SUPPLIER_HOUSE = {"s-fabric-cathynordstrom": "h-cathy-nordstrom"}

# fabric material id → house/collection/pattern/colourway
FABRIC_META = {
    "m-001": {"house_id": "h-coordonne", "collection": "Edinburgh", "pattern": "Vibrant", "colourway": "Moss / Indigo / Clay (3 shown — confirm)", "repeat_cm": 8.8, "fabric_type": "pattern"},
    "m-002": {"house_id": "h-cathy-nordstrom", "collection": None, "pattern": "Faye", "colourway": "Rust and Lilac", "repeat_cm": 12, "fabric_type": "linen"},
    "m-018": {"house_id": "h-william-morris", "collection": None, "pattern": "Honeysuckle & Tulip", "colourway": "FM289-02 blue/off-white/brown", "repeat_cm": 53, "fabric_type": "pattern"},
    "m-019": {"house_id": "h-manuel-canovas", "collection": None, "pattern": "Tobago", "colourway": "Greige (M4110-01)", "fabric_type": "velvet"},
    "m-020": {"house_id": "h-casamance", "collection": None, "pattern": "(range — confirm per listing)", "colourway": None, "fabric_type": "pattern"},
}

# interior material id → layer role + foam spec
INTERIOR_META = {
    "m-003": {"layer_role": "core", "unit_kind": "sheet", "density_kg_m3": 38, "hardness_n": 150, "thickness_cm": 4, "sheet_w_cm": 120, "sheet_l_cm": 200},
    "m-015": {"layer_role": "core", "unit_kind": "sheet", "density_kg_m3": 38, "hardness_n": 150, "thickness_cm": 3, "sheet_w_cm": 120, "sheet_l_cm": 200},
    "m-004": {"layer_role": "body_wadding", "unit_kind": "length_m"},
    "m-005": {"layer_role": "top_wadding", "unit_kind": "length_m"},
    "m-006": {"layer_role": "liner", "unit_kind": "length_m"},
    "m-007": {"layer_role": "suspension", "unit_kind": "length_m"},
    "m-008": {"layer_role": "cover", "unit_kind": "piece", "fabric_type": "sheepskin"},
    "m-009": {"layer_role": "adhesive", "unit_kind": "can"},
    "m-010": {"unit_kind": "pack"},
    "m-011": {"unit_kind": "spool"},
    "m-012": {"unit_kind": "can"},
    "m-013": {"unit_kind": "pack"},
    "m-014": {"unit_kind": "piece"},
    "m-016": {"unit_kind": "piece"},
    "m-017": {"unit_kind": "piece"},
}

COUNTRY_VAT = {"Sweden": ("inc_25", 0.25), "Spain": ("inc_25", 0.21), "France": ("inc_25", 0.20), "UK": ("inc_20", 0.20), "Denmark": ("inc_25", 0.25)}

# Extra suppliers that only appear in the research price tables (verified live, Sep 2026)
EXTRA_SUPPLIERS = [
    {"id": "s-originellt", "name": "Originellt.se", "kind": "textile_supplier", "trade": "cotton felt (bomullsvadd)", "country": "Sweden", "website": "https://originellt.se", "vat_treatment": "inc_25", "ships_to_sweden": True, "notes": "100% bomull 450 g/m², 100 cm. research/material-suppliers.md §4."},
    {"id": "s-green-living", "name": "Green Living Interiör", "kind": "textile_supplier", "trade": "cotton felt, jute webbing", "country": "Sweden", "website": "https://www.glinterior.se", "vat_treatment": "inc_25", "ships_to_sweden": True, "notes": "Cheapest cotton felt found (149 kr/m). Site also lists a 60 cm width — verify before ordering."},
    {"id": "s-mondial-tissus", "name": "Mondial Tissus", "kind": "textile_supplier", "trade": "wool wadding", "country": "Sweden", "website": "https://www.mondialtissus.se", "vat_treatment": "inc_25", "ships_to_sweden": True, "notes": "150 cm wide, 120 g/m² — light, may need double layer."},
    {"id": "s-museiservice", "name": "Museiservice", "kind": "textile_supplier", "trade": "calico / lakansväv", "country": "Sweden", "website": "https://museiservice.se", "vat_treatment": "inc_25", "ships_to_sweden": True, "notes": "30 m roll = 2,400 kr (80 kr/m equiv). Bulk only."},
    {"id": "s-nordisk-textil", "name": "Nordisk Textil", "kind": "textile_supplier", "trade": "jute webbing", "country": "Sweden", "website": "https://nordisktextil.se", "vat_treatment": "inc_25", "ships_to_sweden": True, "notes": "50 mm sadelgjord, 25 m roll."},
    {"id": "s-ptv", "name": "PTV.se", "kind": "textile_supplier", "trade": "Gabriel fabrics", "country": "Sweden", "website": "https://ptv.se", "vat_treatment": "inc_25", "ships_to_sweden": True, "notes": "Gabriel Savak Plain 2,660 kr/m inc VAT, min 1 m — verified live."},
    {"id": "s-schaumstoffonline", "name": "Schaumstoffonline.de", "kind": "textile_supplier", "trade": "cold foam cut to size", "country": "Germany", "website": "https://schaumstoffonline.de", "vat_treatment": "unknown", "ships_to_sweden": None, "shipping_note": "Free shipping >€100 within DE; Sweden delivery + border friction untested. Cross-border foam has failed in practice before (Fikstura, DHL costs) — trial order first.", "notes": "RG40 Kaltschaum €7.38/m²/cm. ~87% cheaper per metre than Möbelbiten before freight."},
]

# Extra materials only present in the research (so offers have something to hang on)
EXTRA_MATERIALS = [
    {"id": "m-021", "name": "Kallskum 38 kg/m³, 5 cm", "category": "interior", "layer_role": "core", "unit_kind": "sheet", "composition": "cold-cure PU foam", "width_cm": 120, "density_kg_m3": 38, "hardness_n": 150, "thickness_cm": 5, "sheet_w_cm": 120, "sheet_l_cm": 200, "status": "active"},
    {"id": "m-022", "name": "Kallskum 44 kg/m³ (Nevotex), 3–5 cm", "category": "interior", "layer_role": "core", "unit_kind": "sheet", "composition": "cold-cure PU foam, OEKO-TEX", "width_cm": 120, "density_kg_m3": 44, "hardness_n": 195, "sheet_w_cm": 120, "sheet_l_cm": 200, "status": "watch", "notes": "The high-end default spec (≥40 kg/m³, 195 N). Price behind trade login."},
    {"id": "m-023", "name": "Wool wadding, 120 g/m² (85% wool)", "category": "interior", "layer_role": "top_wadding", "unit_kind": "length_m", "composition": "85% wool / 15% polylactide", "width_cm": 150, "weight_gsm": 120, "status": "watch", "notes": "Light — may need a double layer for the 'full' tier."},
    {"id": "m-024", "name": "Calico / lakansväv, 150 cm", "category": "interior", "layer_role": "liner", "unit_kind": "length_m", "composition": "100% cotton, ~150 g/m²", "width_cm": 150, "weight_gsm": 150, "status": "active"},
    {"id": "m-025", "name": "Jute webbing, 35 mm", "category": "interior", "layer_role": "suspension", "unit_kind": "length_m", "composition": "100% jute", "width_cm": 3.5, "status": "active"},
    {"id": "m-026", "name": "Jute webbing, 50 mm", "category": "interior", "layer_role": "suspension", "unit_kind": "length_m", "composition": "100% jute", "width_cm": 5, "status": "active"},
    {"id": "m-027", "name": "Gabriel — Savak Plain", "category": "fabric", "layer_role": "cover", "unit_kind": "length_m", "house_id": "h-gabriel", "pattern": "Savak", "tier": "quality", "fabric_type": "wool", "composition": "100% wool", "width_cm": 140, "martindale": 100000, "status": "active", "notes": "Proven resale fabric. fabrics.md decision table."},
]

# (material_id, supplier_id, price, unit, currency, extra)
EXTRA_OFFERS = [
    ("m-004", "s-originellt", 169, "per m", "SEK", {"width_cm": 100, "source_url": "https://originellt.se/vit-bomullsvadd", "notes": "100% bomull (Möbelbiten's is 85/15)."}),
    ("m-004", "s-green-living", 149, "per m", "SEK", {"width_cm": 100, "source_url": "https://www.glinterior.se/sv-SE/product/bomullsvadd-450g-100cm", "availability_note": "Site also lists 60 cm — verify width before ordering.", "notes": "65–75% bomull. Cheapest found."}),
    ("m-021", "s-foam-mobelbiten", 1779, "per 120x200cm sheet", "SEK", {"source_url": "https://mobelbiten.se/products/kallskum"}),
    ("m-015", "s-ostersjokompaniet", 1025, "per 120x200cm sheet", "SEK", {"source_url": "https://www.ostersjokompaniet.se/stoppning-isolering/skumplast/kallskum-38kg/kallskum-38-kg-5", "availability_note": "Page says 'kan endast köpas med en säljplan' — may need a trade account. Sheet size assumed 120×200, unconfirmed. See tasks t-002.", "notes": "~12% cheaper per cm than Möbelbiten, in stock 1–2 days."}),
    ("m-021", "s-ostersjokompaniet", 1670, "per 120x200cm sheet", "SEK", {"source_url": "https://www.ostersjokompaniet.se/stoppning-isolering/skumplast/kallskum-38kg/kallskum-38-kg-5", "availability_note": "Same trade-account caveat as the 3 cm."}),
    ("m-022", "s-nevotex", None, "per 120x200cm sheet", "SEK", {"source_url": "https://nevotex.se/produkter/ovrigt/stoppningsmaterial-polyeter/polyeter-kallskum/kallskum-44-kg-m3/kallskum-44-kg-m", "availability_note": "Price behind trade login — account pending (3-week wait on company number)."}),
    ("m-003", "s-schaumstoffonline", 8.86, "per m (120 cm wide, 4 cm)", "EUR", {"vat_rate": 0.19, "source_url": "https://schaumstoffonline.de/products/kaltschaum-zuschnitt-rg40", "availability_note": "€7.38/m²/cm, cut to size. Freight to Sweden untested.", "notes": "RG40 (40 kg/m³) — better spec than Möbelbiten 38."}),
    ("m-023", "s-mondial-tissus", 219, "per m", "SEK", {"width_cm": 150, "source_url": "https://www.mondialtissus.se/ullvadd-naturlig-ull-fran-frankrike-120-g-297037.html"}),
    ("m-024", "s-museiservice", 80, "per m", "SEK", {"width_cm": 150, "min_order": "30 m roll (2,400 kr)", "source_url": "https://museiservice.se/products/bomullsv-v-oblekt-150cm-30-lpm"}),
    ("m-025", "s-green-living", 36, "per m", "SEK", {"source_url": "https://www.glinterior.se/sv-SE/product/sadelgjord-jute-35"}),
    ("m-026", "s-nordisk-textil", 59, "per m", "SEK", {"min_order": "25 m roll", "source_url": "https://nordisktextil.se/sv/products/sadelgjord-50mm"}),
    ("m-027", "s-ptv", 2660, "per m", "SEK", {"min_order": "1 m", "source_url": "https://ptv.se", "notes": "Verified live."}),
]


def main():
    if WRITE and (not BASE or not KEY):
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set.")
    print("MODE:", "WRITE" if WRITE else "DRY RUN (add --write to apply)")

    mats_json = load("materials.json")["materials"]
    sups_json = load("suppliers.json")["suppliers"]
    costs_json = load("piece_costings.json")["costings"]

    # -------------------------------------------------------------- suppliers
    suppliers = []
    for s in sups_json:
        if s["name"].startswith("SAMPLE"):
            continue
        row = {
            "id": s["id"], "name": s["name"], "kind": s.get("kind"), "trade": s.get("trade"),
            "country": s.get("country"), "phone": s.get("phone"), "email": s.get("email"),
            "rating": s.get("rating"), "notes": s.get("notes"),
            "house_id": SUPPLIER_HOUSE.get(s["id"]),
            "vat_treatment": COUNTRY_VAT.get(s.get("country"), ("unknown", 0.25))[0],
            "ships_to_sweden": True if s.get("country") == "Sweden" else None,
        }
        if s["id"] == "s-fabric-casamance":
            row["name"] = "chicandfabric.com"
            row["trade"] = "pattern fabric retailer — Casamance, Coordonné, Güell Lamadrid"
        suppliers.append(row)
    suppliers += EXTRA_SUPPLIERS
    sup_country = {s["id"]: s.get("country") for s in suppliers}

    # -------------------------------------------------------------- materials + offers + images
    materials, offers, images = [], [], []
    offer_n = 0
    for m in mats_json:
        row = {
            "id": m["id"], "name": m["name"], "category": m["category"],
            "subcategory": m.get("subcategory"), "composition": m.get("composition"),
            "width_cm": m.get("width_cm"), "weight_gsm": m.get("weight_gsm"),
            "martindale": m.get("martindale"), "notes": None, "status": "active",
            "unit_kind": "length_m" if (m.get("unit") or "").startswith("per m") else "piece",
        }
        if m["category"] == "fabric":
            row.update({"tier": "pattern", "layer_role": "cover", "unit_kind": "length_m", "fire_cert": "not published"})
            row.update(FABRIC_META.get(m["id"], {}))
        row.update(INTERIOR_META.get(m["id"], {}))
        # the research/judgement text lived in price_note — keep it on the material as notes
        if m.get("price_note"):
            row["notes"] = m["price_note"]
        materials.append(row)

        if m.get("supplier"):
            offer_n += 1
            country = sup_country.get(m["supplier"])
            vat_kind, vat_rate = COUNTRY_VAT.get(country, ("unknown", 0.25))
            offers.append({
                "id": f"mo-{offer_n:03d}", "material_id": m["id"], "supplier_id": m["supplier"],
                "price": m.get("price"), "currency": m.get("currency") or "SEK", "unit": m.get("unit") or "per m",
                "vat_included": True, "vat_rate": vat_rate,
                "price_ex_vat_override": m.get("price_ex_vat"),
                "source_url": m.get("source_url"), "checked": m.get("checked") or CHECKED,
                "is_default": True,
            })
        for i, img in enumerate(m.get("images") or []):
            colour = None
            stem = img.rsplit(".", 1)[0]
            for suffix in ("-indigo", "-clay", "-detail"):
                if stem.endswith(suffix):
                    colour = suffix[1:]
            images.append({"material_id": m["id"], "storage_path": f"{m['id']}/{img}", "colourway": colour, "position": i, "verified": True, "_local": img})

    materials += EXTRA_MATERIALS
    for (mid, sid, price, unit, cur, extra) in EXTRA_OFFERS:
        offer_n += 1
        country = sup_country.get(sid)
        vat_kind, vat_rate = COUNTRY_VAT.get(country, ("unknown", 0.25))
        row = {"id": f"mo-{offer_n:03d}", "material_id": mid, "supplier_id": sid, "price": price, "currency": cur,
               "unit": unit, "vat_included": True, "vat_rate": vat_rate, "checked": CHECKED, "is_default": False}
        row.update(extra)
        offers.append(row)

    # -------------------------------------------------------------- costings (verbatim)
    RECIPE_MAP = {
        "pcost-001": ("dining-seat", 45, 43, None, None, 2),
        "pcost-002": ("dining-seat-back", 45, 43, 40, 35, 2),
        "pcost-003": ("piano-bench-solo", 80, 55, None, None, 1),
        "pcost-004": ("armchair-full", 72, 75, 65, 60, 1),
    }
    costings, clines = [], []
    for c in costs_json:
        rid, w, d, bw, bd, n = RECIPE_MAP.get(c["id"], (None, None, None, None, None, 1))
        cover = next((l for l in c["lines"] if l.get("material")), None)
        cover_offer = next((o["id"] for o in offers if cover and o["material_id"] == cover["material"] and o["is_default"]), None)
        costings.append({
            "id": c["id"], "piece_id": c.get("piece"), "title": c.get("title"), "recipe_id": rid,
            "width_cm": w, "depth_cm": d, "back_width_cm": bw, "back_depth_cm": bd, "pieces_in_set": n,
            "cover_material_id": cover["material"] if cover else None, "cover_offer_id": cover_offer,
            "cover_metres": cover["qty"] if cover and cover.get("unit") == "m" else None,
            "labour_hours": c.get("labour_hours"), "labour_rate": c.get("labour_rate") or 500,
            "asking_price": c.get("asking_price"), "pair_asking_price": c.get("pair_asking_price"),
            "status": "active", "notes": c.get("notes"), "checked": c.get("checked"),
            "snapshot": {
                "source": "migrated verbatim from data/piece_costings.json",
                "materials_inc_vat": c.get("materials_inc_vat"), "materials_ex_vat": c.get("materials_ex_vat"),
                "labour_cost": c.get("labour_cost"),
                "total_cost_inc_vat": c.get("total_cost_inc_vat"), "total_cost_ex_vat": c.get("total_cost_ex_vat"),
                "vat_rate": c.get("vat_rate"),
            },
        })
        for i, l in enumerate(c["lines"]):
            clines.append({
                "costing_id": c["id"], "position": i, "role": "cover" if l.get("material") else "other",
                "label": l["label"], "material_id": l.get("material"),
                "offer_id": next((o["id"] for o in offers if l.get("material") and o["material_id"] == l["material"] and o["is_default"]), None),
                "qty": l.get("qty"), "unit": l.get("unit"),
                "price_inc_vat": l.get("price_inc_vat"), "price_ex_vat": l.get("price_ex_vat"),
                "is_manual": True, "qty_pinned": True, "note": l.get("note"),
            })

    # -------------------------------------------------------------- write
    print("\nhouses");     upsert("houses", HOUSES)
    print("suppliers");    upsert("suppliers", suppliers)
    print("materials");    upsert("materials", materials)
    print("offers");       upsert("material_offers", offers)
    print("costings");     upsert("costings", costings)
    if WRITE:
        # lines have no natural key — clear and reinsert for the migrated costings
        for cid in {l["costing_id"] for l in clines}:
            req("DELETE", f"/rest/v1/costing_lines?costing_id=eq.{cid}")
        req("DELETE", "/rest/v1/material_images?material_id=like.m-*")
    print("costing_lines")
    if WRITE:
        print(f"  costing_lines: {len(clines)} rows")
        req("POST", "/rest/v1/costing_lines", normalise_keys(clines), {"Prefer": "return=minimal"})
    else:
        upsert("costing_lines", clines)
    print(f"images: {len(images)} files → bucket 'materials'")
    for im in images:
        local = os.path.join(ROOT, "_assets", "materials", im.pop("_local"))
        if not os.path.exists(local):
            print("   missing", local); continue
        print("   ", im["storage_path"])
        upload_image(local, im["storage_path"])
    if WRITE and images:
        req("POST", "/rest/v1/material_images", normalise_keys(images), {"Prefer": "return=minimal"})

    print("\nSummary:", len(HOUSES), "houses ·", len(suppliers), "suppliers ·", len(materials), "materials ·",
          len(offers), "offers ·", len(images), "images ·", len(costings), "costings ·", len(clines), "lines")
    if not WRITE:
        print("Dry run only. Re-run with --write to apply.")


if __name__ == "__main__":
    main()
