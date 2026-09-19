/* Vedda Studio — costing engine.
 * Pure functions, no DOM, no Supabase. Loaded as a plain <script> in the app
 * (window.VeddaCosting) and require()-able from node for tests.
 *
 * Rules implemented (sources in research/costing.md, material-suppliers.md §7,
 * fabrics.md, CLAUDE.md):
 *  - padded area = (w + 2a) × (d + 2a), a = wrap allowance per side (additive, not a %)
 *  - length goods: metres = area ÷ width, rounded UP to 0.05 m
 *  - foam: sheet nesting, cost = sheet price ÷ pieces per sheet
 *  - batting tiers thin / medium / full; armchair seat face doubled wool
 *  - VAT per offer: ex = override ?? (inc ? price ÷ (1 + rate) : price)
 *  - checks: 50 % markup, 6 000 kr floor (pair-aware), fabric ≤ 25–30 % of sale,
 *    kr/hour bands 500 / 300, seat suitability (≥25 000 Martindale AND ≥450 g/m²),
 *    natural-claim consistency (PU foam in the core ⇒ no "fully natural")
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.VeddaCosting = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MIN_MARKUP = 0.5;
  var PRICE_FLOOR = 6000;
  var FABRIC_SHARE_OK = 0.25;
  var FABRIC_SHARE_MAX = 0.30;
  var SEAT_MARTINDALE = 25000;
  var SEAT_GSM = 450;
  var RATE_SCALE = 500;
  var RATE_ADJUST = 300;

  function roundUp(value, step) {
    return Math.ceil(value / step - 1e-9) * step;
  }
  function round2(v) { return Math.round(v * 100) / 100; }
  function round0(v) { return Math.round(v); }

  // ---------------------------------------------------------------- prices
  function fxRate(fx, currency) {
    if (!currency || currency === "SEK") return 1;
    var row = fx && fx[currency];
    return row ? Number(row.rate_to_sek || row) : null;
  }

  /** Unit price of an offer in SEK, ex and inc VAT. Returns nulls if no price. */
  function offerUnitPrice(offer, fx) {
    if (!offer || offer.price == null) return { inc: null, ex: null, approx: false, currency: offer && offer.currency };
    var rate = fxRate(fx, offer.currency);
    if (rate == null) return { inc: null, ex: null, approx: true, currency: offer.currency, missing_fx: true };
    var vat = Number(offer.vat_rate == null ? 0.25 : offer.vat_rate);
    var price = Number(offer.price) * rate;
    var inc, ex;
    if (offer.price_ex_vat_override != null) {
      ex = Number(offer.price_ex_vat_override) * rate;
      inc = offer.vat_included ? price : ex * (1 + vat);
    } else if (offer.vat_included === false) {
      ex = price;
      inc = price * (1 + vat);
    } else {
      inc = price;
      ex = price / (1 + vat);
    }
    return { inc: inc, ex: ex, approx: rate !== 1, currency: offer.currency };
  }

  // ---------------------------------------------------------------- geometry
  function paddedAreaM2(w, d, allowancePerSide) {
    var a = allowancePerSide || 0;
    return ((Number(w) + 2 * a) * (Number(d) + 2 * a)) / 10000;
  }

  function lengthMetres(areaM2, widthCm, roundStep) {
    var widthM = Number(widthCm) / 100;
    if (!widthM) return null;
    return roundUp(areaM2 / widthM, roundStep || 0.05);
  }

  function piecesPerSheet(sheetW, sheetL, w, d, trim) {
    var t = trim || 0;
    var across = Math.floor(sheetW / (Number(w) + t));
    var down = Math.floor(sheetL / (Number(d) + t));
    // try the rotated nesting too, take the better one
    var across2 = Math.floor(sheetW / (Number(d) + t));
    var down2 = Math.floor(sheetL / (Number(w) + t));
    return Math.max(across * down, across2 * down2, 1);
  }

  function webbingMetres(w, d) {
    // strips every 10 cm each way, +20 cm tacking allowance per strip
    var nW = Math.ceil(Number(w) / 10);
    var nD = Math.ceil(Number(d) / 10);
    return roundUp((nW * (Number(d) + 20) + nD * (Number(w) + 20)) / 100, 0.5);
  }

  // ---------------------------------------------------------------- lines
  function line(o) {
    return {
      role: o.role,
      label: o.label,
      material_id: o.material ? o.material.id : null,
      offer_id: o.offer ? o.offer.id : null,
      qty: o.qty == null ? null : round2(o.qty),
      unit: o.unit || "",
      unit_price_inc: o.unitInc == null ? null : round2(o.unitInc),
      unit_price_ex: o.unitEx == null ? null : round2(o.unitEx),
      price_inc_vat: o.inc == null ? null : round0(o.inc),
      price_ex_vat: o.ex == null ? null : round0(o.ex),
      is_manual: !!o.is_manual,
      approx: !!o.approx,
      missing: !!o.missing,
      note: o.note || ""
    };
  }

  function layerLine(role, label, pick, qty, unit, fx, note, per) {
    if (!pick || !pick.offer) {
      return line({ role: role, label: label + " — no offer picked", qty: qty, unit: unit, missing: true, note: note });
    }
    var p = offerUnitPrice(pick.offer, fx);
    var n = per || 1;
    return line({
      role: role, label: label, material: pick.material, offer: pick.offer,
      qty: qty * n, unit: unit,
      unitInc: p.inc, unitEx: p.ex,
      inc: p.inc == null ? null : p.inc * qty * n,
      ex: p.ex == null ? null : p.ex * qty * n,
      approx: p.approx, missing: p.inc == null, note: note
    });
  }

  /**
   * Compute a costing.
   * @param input {
   *   costing: row from `costings` (+ pieces_in_set, dims, tier, cover_metres, labour…),
   *   recipe:  entry from recipes.json (or null for a fully manual costing),
   *   config:  recipes.json top-level (wrap_allowance_cm_per_side, batting_tiers, defaults),
   *   picks:   { role: { material, offer } } — resolved by the UI; roles: suspension, core,
   *            core_back, body_wadding, top_wadding, liner, cover
   *   manualLines: [{ label, qty, unit, price_inc_vat, price_ex_vat, role, note }]
   *   fx:      { EUR: {rate_to_sek}, ... }
   * }
   */
  function compute(input) {
    var c = input.costing || {};
    var r = input.recipe || null;
    var cfg = input.config || {};
    var picks = input.picks || {};
    var fx = input.fx || {};
    var d = cfg.defaults || {};
    var n = Number(c.pieces_in_set || 1);
    var lines = [];
    var warnings = [];

    var w = Number(c.width_cm || (r && r.default_size_cm && r.default_size_cm.w) || 0);
    var dep = Number(c.depth_cm || (r && r.default_size_cm && r.default_size_cm.d) || 0);
    var bw = Number(c.back_width_cm || (r && r.back_size_cm && r.back_size_cm.w) || 0);
    var bd = Number(c.back_depth_cm || (r && r.back_size_cm && r.back_size_cm.d) || 0);
    var hasBack = !!(r && r.back_size_cm) && bw > 0 && bd > 0;

    var allowanceKey = r ? r.wrap_allowance : null;
    var allowance = allowanceKey && cfg.wrap_allowance_cm_per_side ? cfg.wrap_allowance_cm_per_side[allowanceKey] : 0;
    var seatArea = w && dep ? paddedAreaM2(w, dep, allowance) : 0;
    var backArea = hasBack ? paddedAreaM2(bw, bd, allowance) : 0;
    var area = seatArea + backArea;

    var tierKey = c.batting_tier || (r && r.batting_tier) || "thin";
    var tier = (cfg.batting_tiers && cfg.batting_tiers[tierKey]) || { layers: ["body_wadding"] };
    var roundStep = d.length_round_m || 0.05;
    var trim = d.foam_trim_cm == null ? 2 : d.foam_trim_cm;

    var layers = r ? r.layers.slice() : [];
    var optional = (r && r.optional_layers) || [];

    layers.forEach(function (role) {
      if (role === "top_wadding" && tier.layers.indexOf("top_wadding") < 0) return;
      if (role === "core" && c.keep_original_foam) {
        lines.push(line({ role: "core", label: "Core — original foam kept (passed the four tests)", qty: 0, unit: "", inc: 0, ex: 0, note: "material-suppliers.md §7" }));
        return;
      }
      var pick = picks[role];
      if (!pick && optional.indexOf(role) >= 0) return;

      if (role === "suspension") {
        var m = r.webbing_metres_default != null ? r.webbing_metres_default : webbingMetres(w, dep);
        lines.push(layerLine("suspension", "Jute webbing", pick, m, "m", fx, "strips every 10 cm, +20 cm tacking — estimate", n));
      } else if (role === "core") {
        var mat = pick && pick.material;
        var thick = c.foam_thickness_cm || (r.foam && r.foam.thickness_cm);
        var label = "Foam core" + (thick ? " " + thick + " cm" : "");
        if (mat && mat.sheet_w_cm && mat.sheet_l_cm && w && dep) {
          var per = piecesPerSheet(Number(mat.sheet_w_cm), Number(mat.sheet_l_cm), w, dep, trim);
          lines.push(layerLine("core", label + " (seat)", pick, 1 / per, "sheet", fx, "1/" + per + " of a " + mat.sheet_w_cm + "×" + mat.sheet_l_cm + " cm sheet", n));
          if (hasBack) {
            var pickB = picks.core_back || pick;
            var matB = pickB.material;
            var perB = piecesPerSheet(Number(matB.sheet_w_cm || mat.sheet_w_cm), Number(matB.sheet_l_cm || mat.sheet_l_cm), bw, bd, trim);
            var tB = r.back_foam && r.back_foam.thickness_cm;
            lines.push(layerLine("core_back", "Foam core" + (tB ? " " + tB + " cm" : "") + " (back)", pickB, 1 / perB, "sheet", fx, "1/" + perB + " sheet", n));
          }
        } else if (mat && (mat.unit_kind === "length_m")) {
          var mm = roundUp((dep + trim) / 100, roundStep) + (hasBack ? roundUp((bd + trim) / 100, roundStep) : 0);
          lines.push(layerLine("core", label, pick, mm, "m", fx, "", n));
        } else {
          lines.push(layerLine("core", label, pick, 1, "piece", fx, "", n));
        }
        if (mat && r.foam && r.foam.density_min && mat.density_kg_m3 && Number(mat.density_kg_m3) < Number(r.foam.density_min)) {
          warnings.push("Foam density " + mat.density_kg_m3 + " kg/m³ is below the " + r.foam.density_min + " kg/m³ spec for this item — acceptable for practice pieces only.");
        }
      } else if (role === "body_wadding" || role === "top_wadding" || role === "liner") {
        var matL = pick && pick.material;
        var width = (pick && pick.offer && pick.offer.width_cm) || (matL && matL.width_cm);
        var factor = 1;
        if (role === "top_wadding") {
          factor = tier.top_wadding_factor || 1;
          if (r.top_wadding_seat_factor) factor = factor * Number(r.top_wadding_seat_factor);
        }
        var metres = width ? lengthMetres(area * factor, width, roundStep) : null;
        var labelL = role === "body_wadding" ? "Cotton felt" : role === "top_wadding" ? "Wool wadding" : "Scrim / calico";
        var noteL = width ? area.toFixed(2) + " m² ÷ " + width + " cm width" + (factor !== 1 ? " × " + factor : "") : "no width on material — cannot compute metres";
        lines.push(layerLine(role, labelL, pick, metres == null ? 0 : metres, "m", fx, noteL, n));
      } else if (role === "cover") {
        var metresC = c.cover_metres != null ? Number(c.cover_metres) : Number(r.cover_metres_default || 0);
        var unitC = r.cover_unit || "m";
        var pickC = picks.cover;
        var labelC = "Cover — " + (pickC && pickC.material ? pickC.material.name : "no fabric picked");
        lines.push(layerLine("cover", labelC, pickC, metresC, unitC, fx, unitC === "m" ? "cut list per seating-guide.md §8, editable" : "", n));
      } else if (role === "other") {
        // recipe placeholder for manual-only jobs (leather strap): nothing computed
      }
    });

    // allowances (per piece, inc VAT 25 %) — only where there is an upholstered face
    var upholstered = layers.indexOf("cover") >= 0 && !(r && r.no_foam && layers.length === 1 && layers[0] === "cover");
    if (r) {
      var cons = c.consumables_allowance == null ? (d.consumables_allowance || 0) : Number(c.consumables_allowance);
      if (cons) lines.push(line({ role: "consumables", label: "Consumables allowance (glue, staples, thread, oil, wax)", qty: n, unit: "piece", unitInc: cons, unitEx: cons / 1.25, inc: cons * n, ex: cons / 1.25 * n, approx: true, note: d.consumables_caveat || "" }));
      if (upholstered && d.lining_allowance) lines.push(line({ role: "lining", label: "Lining fabric (underside)", qty: n, unit: "piece", unitInc: d.lining_allowance, unitEx: d.lining_allowance / 1.25, inc: d.lining_allowance * n, ex: d.lining_allowance / 1.25 * n, approx: true }));
      if (upholstered && d.sealing_cotton_allowance) lines.push(line({ role: "sealing", label: "Cotton sealing fabric (edge finish)", qty: n, unit: "piece", unitInc: d.sealing_cotton_allowance, unitEx: d.sealing_cotton_allowance / 1.25, inc: d.sealing_cotton_allowance * n, ex: d.sealing_cotton_allowance / 1.25 * n, approx: true }));
    }

    // manual lines pass through verbatim (frame, brand tag, refinishing, Sarah's own numbers)
    (input.manualLines || []).forEach(function (ml) {
      lines.push(line({
        role: ml.role || "other", label: ml.label, qty: ml.qty, unit: ml.unit,
        inc: ml.price_inc_vat, ex: ml.price_ex_vat == null ? ml.price_inc_vat : ml.price_ex_vat,
        is_manual: true, note: ml.note, missing: ml.price_inc_vat == null
      }));
    });

    // ---------------------------------------------------------------- totals
    var matInc = 0, matEx = 0, missing = 0, approx = false;
    lines.forEach(function (l) {
      if (l.price_inc_vat == null) { missing++; return; }
      matInc += l.price_inc_vat;
      matEx += l.price_ex_vat == null ? l.price_inc_vat : l.price_ex_vat;
      if (l.approx) approx = true;
    });
    var hours = Number(c.labour_hours == null ? (r && r.labour_hours_default) || 0 : c.labour_hours);
    var rate = Number(c.labour_rate == null ? (d.labour_rate || 500) : c.labour_rate);
    var labour = hours * rate;
    var totals = {
      pieces_in_set: n,
      materials_inc_vat: round0(matInc),
      materials_ex_vat: round0(matEx),
      labour_hours: hours,
      labour_rate: rate,
      labour_cost: round0(labour),
      total_cost_inc_vat: round0(matInc + labour),
      total_cost_ex_vat: round0(matEx + labour),
      padded_area_m2: round2(area),
      lines_missing_price: missing,
      has_estimates: approx
    };

    // ---------------------------------------------------------------- checks
    // Computed from the FINAL lines/totals only (never re-derived from recipe
    // layers) — a costing with verbatim/manual lines (e.g. migrated ones)
    // must not have synthetic recipe lines added on top when checking it.
    var cover = picks.cover && picks.cover.material;
    var core = picks.core && picks.core.material;
    var coreIsPuFoam = !!(core && !c.keep_original_foam && /kallskum|polyeter|polyether|\bpu\b|schaum/i.test((core.name || "") + " " + (core.composition || "")));
    var res = evaluateChecks(c, totals, lines, cover, coreIsPuFoam);

    return { lines: lines, totals: totals, checks: res.checks, warnings: warnings, effective_ask: res.effective_ask };
  }

  /**
   * Checks from already-finalised totals/lines — no recipe/layer knowledge
   * needed. Safe to call on a frozen snapshot's stored lines/totals, or on
   * compute()'s live output. coverMaterial (for the seat-suitability check)
   * and coreIsPuFoam (for the natural-claim check) are optional context.
   */
  function evaluateChecks(c, totals, lines, coverMaterial, coreIsPuFoam) {
    var n = Number(c.pieces_in_set || 1);
    var ask = c.asking_price == null ? null : Number(c.asking_price);
    var pairAsk = c.pair_asking_price == null ? null : Number(c.pair_asking_price);
    var effectiveAsk = n > 1 ? (pairAsk != null ? pairAsk : (ask != null ? ask * n : null)) : (pairAsk != null ? pairAsk : ask);
    var checks = [];

    if (effectiveAsk != null && totals.total_cost_ex_vat) {
      var markup = (effectiveAsk - totals.total_cost_ex_vat) / totals.total_cost_ex_vat;
      checks.push({ id: "markup", ok: markup >= MIN_MARKUP, value: markup,
        text: (markup >= MIN_MARKUP ? "✓ " : "✗ ") + Math.round(markup * 100) + "% markup (min 50%)" });
    } else {
      checks.push({ id: "markup", ok: null, text: "— markup: no asking price" });
    }

    var perPieceAsk = effectiveAsk == null ? null : effectiveAsk / n;
    if (perPieceAsk != null) {
      var floorOk = perPieceAsk >= PRICE_FLOOR || (n > 1 && effectiveAsk >= PRICE_FLOOR);
      checks.push({ id: "floor", ok: floorOk, value: perPieceAsk,
        text: (floorOk ? "✓ " : "✗ ") + fmt(effectiveAsk) + (n > 1 ? " for the set" : "") + " vs " + fmt(PRICE_FLOOR) + " price floor" });
    }

    var coverLine = (lines || []).filter(function (l) { return l.role === "cover" && l.price_ex_vat != null; })[0];
    if (coverLine && effectiveAsk) {
      var share = coverLine.price_ex_vat / effectiveAsk;
      var shareOk = share <= FABRIC_SHARE_OK ? true : share <= FABRIC_SHARE_MAX ? "warn" : false;
      checks.push({ id: "fabric_share", ok: shareOk, value: share,
        text: (shareOk === true ? "✓ " : shareOk === "warn" ? "⚠ " : "✗ ") + "fabric is " + Math.round(share * 100) + "% of sale (≤25–30%)" });
    }

    if (effectiveAsk != null && totals.labour_hours) {
      var perHour = (effectiveAsk - totals.materials_ex_vat) / totals.labour_hours;
      var band = perHour >= RATE_SCALE ? "scale" : perHour >= RATE_ADJUST ? "adjust" : "stop";
      checks.push({ id: "kr_per_hour", ok: band === "scale" ? true : band === "adjust" ? "warn" : false, value: perHour, band: band,
        text: (band === "scale" ? "✓ " : band === "adjust" ? "⚠ " : "✗ ") + Math.round(perHour) + " kr/hour — " + (band === "scale" ? ">500 scale it" : band === "adjust" ? "300–500 adjust" : "<300 stop") });
    }

    if (coverMaterial) {
      var mart = coverMaterial.martindale == null ? null : Number(coverMaterial.martindale);
      var gsm = coverMaterial.weight_gsm == null ? null : Number(coverMaterial.weight_gsm);
      var seatOk = mart != null && mart >= SEAT_MARTINDALE && (gsm == null || gsm >= SEAT_GSM);
      var txt;
      if (mart == null) txt = "⚠ cover: Martindale not published — ask before buying";
      else if (mart < SEAT_MARTINDALE) txt = "⚠ cover: " + mart.toLocaleString("sv-SE") + " Martindale — light domestic only (seat floor 25,000)";
      else if (gsm != null && gsm < SEAT_GSM) txt = "⚠ cover: " + gsm + " g/m² — below the 450 g/m² heavy-domestic floor";
      else txt = "✓ cover seat-suitable (" + mart.toLocaleString("sv-SE") + " Martindale" + (gsm ? ", " + gsm + " g/m²" : "") + ")";
      checks.push({ id: "seat_suitable", ok: seatOk ? true : "warn", text: txt });
    }

    if (coreIsPuFoam) {
      checks.push({ id: "natural_claim", ok: "warn", text: "⚠ PU foam core — cannot claim \"fully natural interior\" (say \"natural webbing and wool wadding\")" });
    }

    return { checks: checks, effective_ask: effectiveAsk };
  }

  function fmt(v) {
    if (v == null) return "—";
    return Math.round(v).toLocaleString("sv-SE").replace(/ /g, " ") + " kr";
  }

  function seatSuitable(material) {
    if (!material) return null;
    var m = material.martindale == null ? null : Number(material.martindale);
    var g = material.weight_gsm == null ? null : Number(material.weight_gsm);
    if (m == null) return null;
    return m >= SEAT_MARTINDALE && (g == null || g >= SEAT_GSM);
  }

  return {
    compute: compute,
    evaluateChecks: evaluateChecks,
    offerUnitPrice: offerUnitPrice,
    paddedAreaM2: paddedAreaM2,
    lengthMetres: lengthMetres,
    piecesPerSheet: piecesPerSheet,
    webbingMetres: webbingMetres,
    seatSuitable: seatSuitable,
    fmt: fmt,
    constants: { MIN_MARKUP: MIN_MARKUP, PRICE_FLOOR: PRICE_FLOOR, SEAT_MARTINDALE: SEAT_MARTINDALE, SEAT_GSM: SEAT_GSM }
  };
});
