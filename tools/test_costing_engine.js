// node tools/test_costing_engine.js — checks docs/app/costing.js against research/costing.md
const path = require("path");
const C = require(path.join(__dirname, "..", "docs", "app", "costing.js"));
const cfg = require(path.join(__dirname, "..", "docs", "app", "recipes.json"));
const recipe = (id) => cfg.recipes.find((r) => r.id === id);

const mobelbiten = { id: "s-foam-mobelbiten" };
const mats = {
  foam4: { id: "m-003", name: "Kallskum 38 kg/m³, 4 cm", unit_kind: "sheet", sheet_w_cm: 120, sheet_l_cm: 200, density_kg_m3: 38, thickness_cm: 4 },
  foam3: { id: "m-015", name: "Kallskum 38 kg/m³, 3 cm", unit_kind: "sheet", sheet_w_cm: 120, sheet_l_cm: 200, density_kg_m3: 38, thickness_cm: 3 },
  felt: { id: "m-004", name: "Cotton felt, 450 g/m²", unit_kind: "length_m", width_cm: 100 },
  wool: { id: "m-005", name: "Wool wadding, 300 g/m²", unit_kind: "length_m", width_cm: 75 },
  scrim: { id: "m-006", name: "Scrim / calico", unit_kind: "length_m", width_cm: 157 },
  cathy: { id: "m-002", name: "Cathy Nordström — Faye", martindale: 20000, width_cm: 135 },
  tobago: { id: "m-019", name: "Manuel Canovas — Tobago, Greige", martindale: 40000, weight_gsm: 680, width_cm: 140 },
};
const offer = (mid, price, unit, extra) => Object.assign({ id: "mo-" + mid, material_id: mid, supplier_id: mobelbiten.id, price, unit, currency: "SEK", vat_included: true, vat_rate: 0.25 }, extra || {});
const pick = (m, o) => ({ material: m, offer: o });

let failures = 0;
function expect(label, got, want, tol = 0.5) {
  const ok = Math.abs(got - want) <= tol;
  console.log((ok ? "  ok  " : "  FAIL") + " " + label + ": got " + got + ", want " + want);
  if (!ok) failures++;
}

// ------------------------------------------------------------ Item 1 corrected
console.log("Item 1 — dining seat 45×43, +5 cm/side, thin tier");
let out = C.compute({
  costing: { width_cm: 45, depth_cm: 43, pieces_in_set: 1, labour_hours: 2, asking_price: 6000, consumables_allowance: 100 },
  recipe: recipe("dining-seat"), config: cfg,
  picks: { core: pick(mats.foam4, offer("m-003", 1529, "per 120x200cm sheet")), body_wadding: pick(mats.felt, offer("m-004", 169, "per m")), liner: pick(mats.scrim, offer("m-006", 119, "per m")), cover: pick(mats.tobago, offer("m-019", 1656, "per m", { price_ex_vat_override: 1260 })) },
  manualLines: [{ label: "Frame", qty: 1, unit: "piece", price_inc_vat: 160, price_ex_vat: 160 }],
});
const L = (role) => out.lines.find((l) => l.role === role);
expect("padded area m²", out.totals.padded_area_m2, 0.29, 0.005);
expect("foam pieces per sheet → cost", L("core").price_inc_vat, 191, 1);            // 1529/8
expect("felt metres (0.29 ÷ 1.0 → 0.30)", L("body_wadding").qty, 0.30, 0.001);
expect("felt cost", L("body_wadding").price_inc_vat, 51, 1);
expect("scrim metres (0.29 ÷ 1.57 → 0.20)", L("liner").qty, 0.20, 0.001);
expect("cover 0.5 m × 1656", L("cover").price_inc_vat, 828, 1);
expect("cover ex-VAT uses override 1260 × 0.5", L("cover").price_ex_vat, 630, 1);
console.log("  checks:", out.checks.map((c) => c.text).join(" | "));
console.log("  totals:", JSON.stringify(out.totals));

// ------------------------------------------------------------ Item 2 — piano bench (Sarah's actuals)
console.log("\nItem 2 — piano bench 80×55, 3 cm foam, medium tier");
out = C.compute({
  costing: { width_cm: 80, depth_cm: 55, pieces_in_set: 1, labour_hours: 2, asking_price: 3500, cover_metres: 1, consumables_allowance: 50 },
  recipe: recipe("piano-bench-solo"), config: cfg,
  picks: { core: pick(mats.foam3, offer("m-015", 1199, "per 120x200cm sheet")), body_wadding: pick(mats.felt, offer("m-004", 169, "per m")), top_wadding: pick(mats.wool, offer("m-005", 169, "per m")), liner: pick(mats.scrim, offer("m-006", 119, "per m")), cover: pick(mats.cathy, offer("m-002", 862, "per piece")) },
  manualLines: [{ label: "Frame", qty: 1, unit: "piece", price_inc_vat: 300, price_ex_vat: 300 }],
});
// Sarah's sheet used 0.44 m² (no wrap allowance); engine adds +6 cm/side → (92×67) = 0.62 m². Report, don't force.
console.log("  padded area:", out.totals.padded_area_m2, "(Sarah's sheet: 0.44 without wrap allowance — engine applies +6 cm/side per costing.md correction)");
expect("foam per sheet 120×200 from 80×55 (+2 trim, rotated 2×2)", 1 / L("core").qty, 4, 0.01);
console.log("  NOTE costing.md says ~10 benches per sheet — wrong for the 80×55 cm measured bench (4 fit). Flagged in research/costing.md.");
console.log("  checks:", out.checks.map((c) => c.text).join(" | "));
console.log("  totals:", JSON.stringify(out.totals));

// ------------------------------------------------------------ pair logic (pcost-001)
console.log("\nPair logic — 2 seats, asking 3500 each, pair 6000, stored total ex 2030");
out = C.compute({
  costing: { width_cm: 45, depth_cm: 43, pieces_in_set: 2, labour_hours: 2, asking_price: 3500, pair_asking_price: 6000 },
  recipe: recipe("dining-seat"), config: cfg,
  picks: { core: pick(mats.foam4, offer("m-003", 1529, "per 120x200cm sheet")), body_wadding: pick(mats.felt, offer("m-004", 169, "per m")), liner: pick(mats.scrim, offer("m-006", 119, "per m")), cover: pick(mats.tobago, offer("m-019", 1656, "per m", { price_ex_vat_override: 1260 })) },
  manualLines: [{ label: "Frame (pair)", qty: 1, unit: "pair", price_inc_vat: 160, price_ex_vat: 160 }],
});
console.log("  effective ask:", out.effective_ask, "| checks:", out.checks.map((c) => c.text).join(" | "));
expect("effective ask = pair price", out.effective_ask, 6000, 0);

// ------------------------------------------------------------ offer pricing
console.log("\nOffer pricing");
let p = C.offerUnitPrice({ price: 60, currency: "EUR", vat_included: true, vat_rate: 0.21 }, { EUR: { rate_to_sek: 11.5 } });
expect("EUR 60 inc 21% → SEK inc", p.inc, 690, 0.01);
expect("EUR 60 inc 21% → SEK ex", p.ex, 570.25, 0.01);
p = C.offerUnitPrice({ price: 100, currency: "GBP", vat_included: true, vat_rate: 0.2 }, {});
expect("missing FX → null", p.inc == null ? 1 : 0, 1, 0);
p = C.offerUnitPrice({ price: 1000, currency: "SEK", vat_included: false, vat_rate: 0.25 }, {});
expect("ex-VAT trade price → inc", p.inc, 1250, 0.01);

console.log(failures ? "\n" + failures + " FAILED" : "\nall good");
process.exit(failures ? 1 : 0);
