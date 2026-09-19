/* Vedda Studio — materials / suppliers / costing app. Vanilla JS, hash routes. */
(function () {
  "use strict";
  var API = window.VeddaApi;
  var CE = window.VeddaCosting;
  var S = { data: null, user: null, recipes: null, filters: {} };

  // ---------------------------------------------------------------- utils
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function money(v, cur) { if (v == null || isNaN(v)) return "—"; return Math.round(v).toLocaleString("sv-SE") + " " + (cur || "kr"); }
  function num(v, d) { return v == null || v === "" || isNaN(v) ? "—" : Number(v).toLocaleString("sv-SE", { maximumFractionDigits: d == null ? 2 : d }); }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function byId(list, id) { for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i]; return null; }
  function toast(msg, err) {
    var t = document.createElement("div"); t.className = "toast" + (err ? " err" : ""); t.textContent = msg;
    document.body.appendChild(t); setTimeout(function () { t.remove(); }, err ? 5000 : 2200);
  }
  function opt(v, label, sel) { return '<option value="' + esc(v) + '"' + (String(sel) === String(v) ? " selected" : "") + ">" + esc(label) + "</option>"; }
  function val(form, name) { var el = form.elements[name]; if (!el) return null; if (el.type === "checkbox") return el.checked; var v = el.value.trim(); return v === "" ? null : v; }
  function numv(form, name) { var v = val(form, name); return v == null ? null : Number(String(v).replace(",", ".")); }
  function today() { return new Date().toISOString().slice(0, 10); }

  // ---------------------------------------------------------------- derived
  function supplier(id) { return byId(S.data.suppliers, id); }
  function house(id) { return byId(S.data.houses, id); }
  function material(id) { return byId(S.data.materials, id); }
  function offersFor(mid) { return S.data.offers.filter(function (o) { return o.material_id === mid; }); }
  function imagesFor(mid) { return S.data.images.filter(function (i) { return i.material_id === mid; }); }
  function linesFor(cid) { return S.data.lines.filter(function (l) { return l.costing_id === cid; }); }
  function offerPrice(o) { return CE.offerUnitPrice(o, S.data.fx); }
  function bestOffer(mid) {
    var best = null, bp = null;
    offersFor(mid).forEach(function (o) {
      var p = offerPrice(o);
      if (p.ex == null) return;
      if (bp == null || p.ex < bp) { bp = p.ex; best = o; }
    });
    return best;
  }
  function defaultOffer(mid) {
    var os = offersFor(mid);
    return os.filter(function (o) { return o.is_default; })[0] || bestOffer(mid) || os[0] || null;
  }
  function seatTag(m) {
    if (m.category !== "fabric" && m.layer_role !== "cover") return "";
    var ok = CE.seatSuitable(m);
    if (ok === null) return '<span class="tag tag-neutral seat-badge">Martindale ?</span>';
    return ok ? '<span class="tag tag-accent seat-badge">seat ✓</span>' : '<span class="tag tag-outline seat-badge" style="color:var(--color-caution);border-color:var(--color-caution)">light domestic</span>';
  }
  function imgHtml(m, cls) {
    var ims = imagesFor(m.id);
    if (!ims.length) return '<div class="fig ' + (cls || "ar-square") + '"></div>';
    if (ims.length === 1) return '<div class="fig ' + (cls || "ar-square") + '"><img src="' + esc(API.imageUrl(ims[0].storage_path)) + '" alt="" loading="lazy"></div>';
    var slides = ims.map(function (im, i) { return '<img class="carousel-slide' + (i ? "" : " is-active") + '" src="' + esc(API.imageUrl(im.storage_path)) + '" alt="" data-i="' + i + '" loading="lazy">'; }).join("");
    var dots = ims.map(function (_, i) { return '<button class="carousel-dot' + (i ? "" : " is-active") + '" data-i="' + i + '" type="button"></button>'; }).join("");
    return '<div class="fig ' + (cls || "ar-square") + ' carousel" data-carousel>' + slides +
      '<button class="carousel-nav carousel-prev" type="button">‹</button><button class="carousel-nav carousel-next" type="button">›</button>' +
      '<div class="carousel-dots">' + dots + "</div></div>";
  }
  function wireCarousels(root) {
    $$("[data-carousel]", root).forEach(function (c) {
      var slides = $$(".carousel-slide", c), dots = $$(".carousel-dot", c), i = 0;
      function go(n) { i = (n + slides.length) % slides.length; slides.forEach(function (s, k) { s.classList.toggle("is-active", k === i); }); dots.forEach(function (d, k) { d.classList.toggle("is-active", k === i); }); }
      $(".carousel-prev", c).onclick = function (e) { e.preventDefault(); go(i - 1); };
      $(".carousel-next", c).onclick = function (e) { e.preventDefault(); go(i + 1); };
      dots.forEach(function (d, k) { d.onclick = function () { go(k); }; });
    });
  }

  var CAT_LABEL = { fabric: "Fabric", interior: "Interior materials", consumable: "Consumables", equipment: "Equipment" };
  var ROLE_LABEL = { suspension: "Suspension", core: "Core (foam)", body_wadding: "Body wadding", top_wadding: "Top wadding", liner: "Liner / scrim", adhesive: "Adhesive", cover: "Cover", other: "Other" };
  var FABRIC_TYPES = ["pattern", "wool", "boucle", "corduroy", "mohair", "linen", "velvet", "leather", "sheepskin", "other"];
  var UNITS = ["per m", "per 120x200cm sheet", "per piece", "per pack", "per can", "per spool", "per skin", "per m²"];

  // ---------------------------------------------------------------- dialog
  /** In-app confirm, styled like everything else — never the native browser
   * confirm(), which is blocking, unstyled, and off-brand. */
  function confirmDialog(message, onYes) {
    var root = $("#dialog-root");
    root.innerHTML = '<div class="dialog-backdrop"><div class="dialog">' +
      '<div class="dialog-title">Are you sure?</div>' +
      '<div class="dialog-body">' + esc(message) + "</div>" +
      '<div class="dialog-actions">' +
      '<button type="button" class="btn btn-secondary" data-act="no">Cancel</button>' +
      '<button type="button" class="btn btn-primary" data-act="yes" style="background:var(--color-critical);border-color:var(--color-critical)">Delete</button>' +
      "</div></div></div>";
    function close() { root.innerHTML = ""; }
    $('[data-act="no"]', root).onclick = close;
    $(".dialog-backdrop", root).onclick = function (e) { if (e.target === e.currentTarget) close(); };
    $('[data-act="yes"]', root).onclick = function () {
      var btn = $('[data-act="yes"]', root); btn.disabled = true;
      Promise.resolve(onYes()).then(close).catch(function (e) { close(); toast(e.message || String(e), true); });
    };
  }

  function dialog(title, bodyHtml, onSubmit, opts) {
    opts = opts || {};
    var root = $("#dialog-root");
    root.innerHTML = '<div class="dialog-backdrop"><form class="dialog form" novalidate>' +
      '<div class="dialog-title">' + esc(title) + "</div>" + bodyHtml +
      '<div class="form-error" hidden></div>' +
      '<div class="dialog-actions">' + (opts.deleteLabel ? '<button type="button" class="btn btn-secondary" data-act="delete" style="margin-right:auto;color:var(--color-critical)">' + esc(opts.deleteLabel) + "</button>" : "") +
      '<button type="button" class="btn btn-secondary" data-act="cancel">Cancel</button>' +
      '<button type="submit" class="btn btn-primary">' + esc(opts.submitLabel || "Save") + "</button></div></form></div>";
    var form = $("form", root);
    function close() { root.innerHTML = ""; }
    $('[data-act="cancel"]', root).onclick = close;
    $(".dialog-backdrop", root).onclick = function (e) { if (e.target === e.currentTarget) close(); };
    if (opts.deleteLabel) $('[data-act="delete"]', root).onclick = function () { confirmDialog("Delete? This cannot be undone.", opts.onDelete); };
    function showErr(e) { var el = $(".form-error", root); el.textContent = e.message || String(e); el.hidden = false; }
    form.onsubmit = function (e) {
      e.preventDefault();
      var btn = $('button[type="submit"]', form); btn.disabled = true;
      Promise.resolve(onSubmit(form)).then(close).catch(function (err) { showErr(err); btn.disabled = false; });
    };
    if (opts.onOpen) opts.onOpen(form);
    var first = $("input,select,textarea", form); if (first) first.focus();
    return form;
  }
  function field(label, inner, wide) { return '<label class="field' + (wide ? " wide" : "") + '"><span style="display:block;margin-bottom:4px;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:color-mix(in srgb,var(--color-text) 62%,transparent)">' + esc(label) + "</span>" + inner + "</label>"; }
  function input(name, value, type, extra) { return '<input class="input" name="' + name + '" type="' + (type || "text") + '" value="' + esc(value == null ? "" : value) + '" ' + (extra || "") + ">"; }
  function select(name, options, value, allowEmpty) { return '<select class="input" name="' + name + '">' + (allowEmpty ? opt("", allowEmpty === true ? "—" : allowEmpty, value) : "") + options.map(function (o) { return Array.isArray(o) ? opt(o[0], o[1], value) : opt(o, o, value); }).join("") + "</select>"; }
  function textarea(name, value) { return '<textarea class="input" name="' + name + '" rows="3">' + esc(value || "") + "</textarea>"; }

  async function reload() { S.data = await API.loadAll(); }

  // ---------------------------------------------------------------- forms
  function supplierForm(existing) {
    var s = existing || {};
    dialog(existing ? "Edit supplier" : "New supplier",
      '<div class="two">' + field("Name", input("name", s.name, "text", "required")) + field("Kind", select("kind", ["textile_supplier", "dealer", "auction", "service", "manufacturer"], s.kind || "textile_supplier")) + "</div>" +
      '<div class="two">' + field("Trade / what they carry", input("trade", s.trade)) + field("Country", input("country", s.country)) + "</div>" +
      '<div class="two">' + field("Website", input("website", s.website, "url")) + field("Email", input("email", s.email, "email")) + "</div>" +
      '<div class="three">' + field("Phone", input("phone", s.phone)) + field("Rating 1–5", input("rating", s.rating, "number", 'min="1" max="5"')) + field("Account", select("account_status", [["none", "no account"], ["requested", "requested"], ["open", "open"]], s.account_status || "none")) + "</div>" +
      '<div class="two">' + field("VAT on their prices", select("vat_treatment", [["inc_25", "incl. 25 % (SE)"], ["inc_20", "incl. 20 % (UK)"], ["ex_reverse_charge", "ex VAT / reverse charge (trade)"], ["unknown", "unknown — confirm"]], s.vat_treatment || "unknown")) +
        field("Ships to Sweden", select("ships_to_sweden", [["true", "yes"], ["false", "no"]], s.ships_to_sweden == null ? "" : String(s.ships_to_sweden), "not checked")) + "</div>" +
      field("Shipping note", input("shipping_note", s.shipping_note)) +
      field("Min order note", input("min_order_note", s.min_order_note)) +
      field("Is a fabric house too?", select("house_id", S.data.houses.map(function (h) { return [h.id, h.name]; }), s.house_id, "no")) +
      field("Notes", textarea("notes", s.notes)),
      async function (f) {
        var row = {
          id: s.id || API.slugId("s", val(f, "name"), S.data.suppliers), name: val(f, "name"), kind: val(f, "kind"), trade: val(f, "trade"), country: val(f, "country"),
          website: val(f, "website"), email: val(f, "email"), phone: val(f, "phone"), rating: numv(f, "rating"), account_status: val(f, "account_status"),
          vat_treatment: val(f, "vat_treatment"), ships_to_sweden: val(f, "ships_to_sweden") == null ? null : val(f, "ships_to_sweden") === "true",
          shipping_note: val(f, "shipping_note"), min_order_note: val(f, "min_order_note"), house_id: val(f, "house_id"), notes: val(f, "notes")
        };
        if (!row.name) throw new Error("Name is required.");
        await API.upsert("suppliers", row); await reload(); route(); toast("Supplier saved");
      },
      existing ? { deleteLabel: "Delete supplier", onDelete: async function () { await API.remove("suppliers", s.id); await reload(); location.hash = "#/suppliers"; } } : {});
  }

  function houseForm(existing, after) {
    var h = existing || {};
    dialog(existing ? "Edit house" : "New fabric house",
      field("Name", input("name", h.name, "text", "required")) +
      '<div class="two">' + field("Country", input("country", h.country)) + field("Website", input("website", h.website, "url")) + "</div>" +
      field("Notes", textarea("notes", h.notes)),
      async function (f) {
        var row = { id: h.id || API.slugId("h", val(f, "name"), S.data.houses), name: val(f, "name"), country: val(f, "country"), website: val(f, "website"), notes: val(f, "notes") };
        if (!row.name) throw new Error("Name is required.");
        await API.upsert("houses", row); await reload(); if (after) after(row.id); else route(); toast("House saved");
      },
      existing ? { deleteLabel: "Delete house", onDelete: async function () { await API.remove("houses", h.id); await reload(); route(); } } : {});
  }

  function materialForm(existing, presetCategory) {
    var m = existing || { category: presetCategory || "fabric" };
    var houses = S.data.houses.map(function (h) { return [h.id, h.name]; });
    var body =
      '<div class="two">' + field("Name", input("name", m.name, "text", "required")) + field("Category", select("category", Object.keys(CAT_LABEL).map(function (k) { return [k, CAT_LABEL[k]]; }), m.category)) + "</div>" +
      '<div class="three">' + field("Layer role (for recipes)", select("layer_role", Object.keys(ROLE_LABEL).map(function (k) { return [k, ROLE_LABEL[k]]; }), m.layer_role, "—")) +
        field("Sold as", select("unit_kind", [["length_m", "by the metre"], ["sheet", "sheet"], ["piece", "piece"], ["pack", "pack"], ["can", "can"], ["spool", "spool"]], m.unit_kind || "length_m")) +
        field("Status", select("status", [["active", "active"], ["watch", "watch (not yet chosen)"], ["rejected", "rejected"]], m.status || "active")) + "</div>" +
      field("Composition", input("composition", m.composition)) +
      '<div class="three">' + field("Width cm", input("width_cm", m.width_cm, "number", 'step="0.1"')) + field("Weight g/m²", input("weight_gsm", m.weight_gsm, "number")) + field("Martindale", input("martindale", m.martindale, "number")) + "</div>" +
      '<fieldset data-cat="fabric"><legend>Fabric</legend>' +
        '<div class="two">' + field("House / brand", select("house_id", houses, m.house_id, "—") + '<button type="button" class="btn-link" data-act="new-house" style="font-size:11px;margin-top:4px">+ new house</button>') + field("Fabric type", select("fabric_type", FABRIC_TYPES, m.fabric_type, "—")) + "</div>" +
        '<div class="three">' + field("Collection", input("collection", m.collection)) + field("Pattern", input("pattern", m.pattern)) + field("Colourway", input("colourway", m.colourway)) + "</div>" +
        '<div class="three">' + field("Tier", select("tier", [["pattern", "1 · pattern (design layer)"], ["quality", "2 · quality (seat layer)"], ["sheepskin", "3 · sheepskin"]], m.tier, "—")) + field("Repeat cm", input("repeat_cm", m.repeat_cm, "number", 'step="0.1"')) + field("Fire cert", input("fire_cert", m.fire_cert == null ? "not published" : m.fire_cert)) + "</div>" +
        field("Natural fibre", select("natural_fibre", [["true", "yes"], ["false", "no"]], m.natural_fibre == null ? "" : String(m.natural_fibre), "—")) +
      "</fieldset>" +
      '<fieldset data-cat="interior"><legend>Foam / interior spec</legend>' +
        '<div class="three">' + field("Density kg/m³", input("density_kg_m3", m.density_kg_m3, "number")) + field("Hardness N", input("hardness_n", m.hardness_n, "number")) + field("Thickness cm", input("thickness_cm", m.thickness_cm, "number", 'step="0.5"')) + "</div>" +
        '<div class="two">' + field("Sheet width cm", input("sheet_w_cm", m.sheet_w_cm, "number")) + field("Sheet length cm", input("sheet_l_cm", m.sheet_l_cm, "number")) + "</div>" +
      "</fieldset>" +
      field("Notes / judgement (Martindale caveats, wrong-house warnings, colourway ambiguity…)", textarea("notes", m.notes));
    dialog(existing ? "Edit material" : "New material", body,
      async function (f) {
        var row = {
          id: m.id || API.nextId("m", S.data.materials), name: val(f, "name"), category: val(f, "category"), layer_role: val(f, "layer_role"), unit_kind: val(f, "unit_kind"), status: val(f, "status"),
          composition: val(f, "composition"), width_cm: numv(f, "width_cm"), weight_gsm: numv(f, "weight_gsm"), martindale: numv(f, "martindale"),
          house_id: val(f, "house_id"), fabric_type: val(f, "fabric_type"), collection: val(f, "collection"), pattern: val(f, "pattern"), colourway: val(f, "colourway"), tier: val(f, "tier"),
          repeat_cm: numv(f, "repeat_cm"), fire_cert: val(f, "fire_cert"), natural_fibre: val(f, "natural_fibre") == null ? null : val(f, "natural_fibre") === "true",
          density_kg_m3: numv(f, "density_kg_m3"), hardness_n: numv(f, "hardness_n"), thickness_cm: numv(f, "thickness_cm"), sheet_w_cm: numv(f, "sheet_w_cm"), sheet_l_cm: numv(f, "sheet_l_cm"),
          notes: val(f, "notes"), subcategory: m.subcategory || null
        };
        if (!row.name) throw new Error("Name is required.");
        if (row.category === "fabric") { row.layer_role = row.layer_role || "cover"; row.unit_kind = row.unit_kind || "length_m"; }
        await API.upsert("materials", row); await reload();
        location.hash = "#/materials/" + row.id; route(); toast("Material saved");
      },
      {
        deleteLabel: existing ? "Delete material" : null,
        onDelete: async function () { await API.remove("materials", m.id); await reload(); location.hash = "#/materials"; },
        onOpen: function (f) {
          function sync() { var c = f.elements.category.value; $$("fieldset[data-cat]", f).forEach(function (fs) { fs.hidden = fs.getAttribute("data-cat") !== c && !(fs.getAttribute("data-cat") === "interior" && c === "interior"); }); }
          f.elements.category.onchange = sync; sync();
          $('[data-act="new-house"]', f).onclick = function () {
            var snapshot = {}; $$("input,select,textarea", f).forEach(function (el) { snapshot[el.name] = el.type === "checkbox" ? el.checked : el.value; });
            houseForm(null, function (hid) { materialForm(existing, presetCategory); var f2 = $("#dialog-root form"); Object.keys(snapshot).forEach(function (k) { if (f2.elements[k]) f2.elements[k].value = snapshot[k]; }); f2.elements.house_id.value = hid; f2.elements.category.onchange(); });
          };
        }
      });
  }

  function offerForm(materialId, existing) {
    var o = existing || { material_id: materialId, vat_included: true, vat_rate: 0.25, currency: "SEK", unit: "per m", checked: today() };
    var sups = S.data.suppliers.map(function (s) { return [s.id, s.name]; });
    dialog(existing ? "Edit offer" : "Add supplier offer — " + material(materialId).name,
      field("Supplier", select("supplier_id", sups, o.supplier_id, "choose…") + '<button type="button" class="btn-link" data-act="new-sup" style="font-size:11px;margin-top:4px">+ new supplier</button>') +
      '<div class="three">' + field("Price (blank = on request)", input("price", o.price, "number", 'step="0.01"')) + field("Currency", select("currency", ["SEK", "EUR", "GBP", "USD", "NOK", "DKK"], o.currency)) + field("Unit", select("unit", UNITS.concat(UNITS.indexOf(o.unit) < 0 && o.unit ? [o.unit] : []), o.unit)) + "</div>" +
      '<div class="three">' + field("Price includes VAT?", select("vat_included", [["true", "yes (retail price)"], ["false", "no (ex VAT / trade)"]], String(o.vat_included))) + field("VAT rate", select("vat_rate", [["0.25", "25 % SE"], ["0.21", "21 % ES"], ["0.20", "20 % UK/FR"], ["0.19", "19 % DE"], ["0", "0 % reverse charge"]], String(o.vat_rate))) + field("Real ex-VAT price (overrides formula)", input("price_ex_vat_override", o.price_ex_vat_override, "number", 'step="0.01"')) + "</div>" +
      '<div class="three">' + field("Width cm (if different)", input("width_cm", o.width_cm, "number")) + field("Min order", input("min_order", o.min_order)) + field("Lead time", input("lead_time", o.lead_time)) + "</div>" +
      field("Availability / access note", input("availability_note", o.availability_note)) +
      '<div class="two">' + field("Source URL", input("source_url", o.source_url, "url")) + field("Checked", input("checked", o.checked, "date")) + "</div>" +
      field("Default offer for this material", select("is_default", [["true", "yes ★"], ["false", "no"]], String(!!o.is_default))) +
      field("Notes", textarea("notes", o.notes)),
      async function (f) {
        var row = {
          id: o.id || API.nextId("mo", S.data.offers), material_id: materialId, supplier_id: val(f, "supplier_id"), price: numv(f, "price"), currency: val(f, "currency"), unit: val(f, "unit"),
          vat_included: val(f, "vat_included") === "true", vat_rate: numv(f, "vat_rate"), price_ex_vat_override: numv(f, "price_ex_vat_override"), width_cm: numv(f, "width_cm"),
          min_order: val(f, "min_order"), lead_time: val(f, "lead_time"), availability_note: val(f, "availability_note"), source_url: val(f, "source_url"), checked: val(f, "checked"),
          is_default: val(f, "is_default") === "true", notes: val(f, "notes")
        };
        if (!row.supplier_id) throw new Error("Pick a supplier.");
        if (row.is_default) { // only one default per material
          var others = offersFor(materialId).filter(function (x) { return x.is_default && x.id !== row.id; });
          for (var i = 0; i < others.length; i++) await API.update("material_offers", others[i].id, { is_default: false });
        }
        await API.upsert("material_offers", row); await reload(); route(); toast("Offer saved");
      },
      {
        deleteLabel: existing ? "Delete offer" : null, onDelete: async function () { await API.remove("material_offers", o.id); await reload(); route(); },
        onOpen: function (f) { $('[data-act="new-sup"]', f).onclick = function () { supplierForm(null); }; }
      });
  }

  // ---------------------------------------------------------------- views
  function setNav(name) { $$("[data-nav]").forEach(function (a) { if (a.getAttribute("data-nav") === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); }); }

  function materialCard(m) {
    var best = bestOffer(m.id), bp = best ? offerPrice(best) : null;
    var specs = [];
    if (m.martindale) specs.push(Number(m.martindale).toLocaleString("sv-SE") + " Martindale");
    if (m.weight_gsm) specs.push(m.weight_gsm + " g/m²");
    if (m.width_cm) specs.push(m.width_cm + " cm wide");
    if (m.density_kg_m3) specs.push(m.density_kg_m3 + " kg/m³");
    if (m.thickness_cm) specs.push(m.thickness_cm + " cm");
    var kicker = m.category === "fabric" && m.house_id ? (house(m.house_id) || {}).name + " — " + [m.pattern, m.colourway].filter(Boolean).join(", ") : m.name;
    var priceLink = best && best.source_url ? ' <a class="btn-link" href="' + esc(best.source_url) + '" target="_blank" rel="noopener" title="open supplier page">↗</a>' : "";
    return '<div class="card matcard status-' + esc(m.status || "active") + '" data-open="#/materials/' + m.id + '" tabindex="0" role="link">' + imgHtml(m) +
      '<div class="card-kicker">' + esc(kicker) + "</div>" +
      '<div class="best-price"><span class="price">' + (bp && bp.ex != null ? money(bp.ex) + ' <span class="text-muted">ex VAT</span>' : "price tbc") + "</span>" +
      (best && best.unit ? '<span class="text-muted" style="font-size:12px">' + esc(best.unit) + "</span>" : "") + priceLink + "</div>" +
      '<div class="tags-row">' + (m.fabric_type || m.subcategory ? '<span class="tag tag-accent-2">' + esc(m.fabric_type || m.subcategory) + "</span>" : "") + seatTag(m) + specs.map(function (s) { return '<span class="tag tag-outline">' + esc(s) + "</span>"; }).join("") + "</div>" +
      "</div>";
  }

  function viewMaterials() {
    setNav("materials");
    var f = S.filters.materials || (S.filters.materials = { q: "", category: "", role: "", supplier: "", seat: false, priced: false });
    var ms = S.data.materials.filter(function (m) {
      if (f.category && m.category !== f.category) return false;
      if (f.role && m.layer_role !== f.role) return false;
      if (f.supplier && !offersFor(m.id).some(function (o) { return o.supplier_id === f.supplier; })) return false;
      if (f.seat && CE.seatSuitable(m) !== true) return false;
      if (f.priced && !bestOffer(m.id)) return false;
      if (f.q) { var hay = (m.name + " " + (m.composition || "") + " " + (m.notes || "") + " " + ((house(m.house_id) || {}).name || "")).toLowerCase(); if (hay.indexOf(f.q.toLowerCase()) < 0) return false; }
      return true;
    });
    var cats = ["fabric", "interior", "consumable", "equipment"];
    var html = '<div class="view-head"><div><span class="kicker">Catalogue</span><h2>Materials</h2></div><div><button class="btn btn-primary" data-act="new-material">+ Material</button></div></div>' +
      '<div class="toolbar">' +
      '<input class="input" name="q" placeholder="search…" value="' + esc(f.q) + '">' +
      '<label>category ' + select("category", cats.map(function (c) { return [c, CAT_LABEL[c]]; }), f.category, "all") + "</label>" +
      '<label>layer ' + select("role", Object.keys(ROLE_LABEL).map(function (k) { return [k, ROLE_LABEL[k]]; }), f.role, "all") + "</label>" +
      '<label>supplier ' + select("supplier", S.data.suppliers.map(function (s) { return [s.id, s.name]; }), f.supplier, "all") + "</label>" +
      '<label class="chk"><input type="checkbox" name="seat"' + (f.seat ? " checked" : "") + "> seat-suitable</label>" +
      '<label class="chk"><input type="checkbox" name="priced"' + (f.priced ? " checked" : "") + "> has price</label>" +
      '<span class="count">' + ms.length + " of " + S.data.materials.length + "</span></div>";
    cats.forEach(function (c) {
      var items = ms.filter(function (m) { return m.category === c; });
      if (!items.length) return;
      var priced = items.filter(function (m) { return bestOffer(m.id); }).length;
      html += '<div class="matcat"><h4>' + CAT_LABEL[c] + ' <span class="text-muted">' + priced + "/" + items.length + ' priced</span></h4><div class="grid-pieces matgrid">' + items.map(materialCard).join("") + "</div></div>";
    });
    if (!ms.length) html += '<div class="empty">Nothing matches.</div>';
    render(html);
    var tb = $(".toolbar");
    tb.oninput = tb.onchange = function () { f.q = tb.elements.q.value; f.category = tb.elements.category.value; f.role = tb.elements.role.value; f.supplier = tb.elements.supplier.value; f.seat = tb.elements.seat.checked; f.priced = tb.elements.priced.checked; viewMaterials(); var q = $(".toolbar input[name=q]"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); };
  }

  function offersTable(mid, editable) {
    var os = offersFor(mid); if (!os.length) return '<div class="empty">No supplier offers yet.</div>';
    var best = bestOffer(mid);
    return '<div class="tablewrap"><table class="table offers-table"><thead><tr><th>Supplier</th><th class="num">Price</th><th class="num">ex VAT (SEK)</th><th>Unit</th><th>Width</th><th>Min / lead</th><th>Checked</th><th>Note</th><th></th></tr></thead><tbody>' +
      os.map(function (o) {
        var p = offerPrice(o), s = supplier(o.supplier_id) || {};
        return '<tr class="' + (o.is_default ? "is-default " : "") + (best && best.id === o.id ? "is-cheapest" : "") + '">' +
          "<td>" + (s.id ? '<a class="btn-link" href="#/suppliers/' + s.id + '">' + esc(s.name) + "</a>" : "—") + (s.account_status === "open" ? ' <span class="tag tag-accent" style="font-size:9px">account</span>' : "") + "</td>" +
          '<td class="num price">' + (o.price == null ? "on request" : num(o.price) + " " + o.currency + (o.vat_included ? "" : " ex")) + "</td>" +
          '<td class="num price">' + (p.ex == null ? "—" : (p.approx ? "≈ " : "") + money(p.ex)) + "</td>" +
          "<td>" + esc(o.unit || "") + "</td><td>" + (o.width_cm ? o.width_cm + " cm" : "") + "</td>" +
          '<td class="wrap">' + esc([o.min_order, o.lead_time].filter(Boolean).join(" · ")) + "</td><td>" + esc(o.checked || "") + "</td>" +
          '<td class="wrap text-muted">' + esc(o.availability_note || o.notes || "") + (o.source_url ? ' <a class="btn-link" href="' + esc(o.source_url) + '" target="_blank" rel="noopener">source</a>' : "") + "</td>" +
          "<td>" + (editable ? '<a class="btn-link" href="#" data-act="edit-offer" data-id="' + o.id + '">edit</a>' : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function viewMaterial(id) {
    setNav("materials");
    var m = material(id); if (!m) return render('<div class="empty">Material not found.</div>');
    var h = house(m.house_id);
    var spec = [["Category", CAT_LABEL[m.category]], ["Layer role", ROLE_LABEL[m.layer_role] || "—"], ["Status", m.status], ["Composition", m.composition], ["Width", m.width_cm ? m.width_cm + " cm" : null], ["Weight", m.weight_gsm ? m.weight_gsm + " g/m²" : null], ["Martindale", m.martindale ? Number(m.martindale).toLocaleString("sv-SE") : null],
      ["House", h ? h.name : null], ["Collection", m.collection], ["Pattern", m.pattern], ["Colourway", m.colourway], ["Tier", m.tier], ["Type", m.fabric_type], ["Repeat", m.repeat_cm ? m.repeat_cm + " cm" : null], ["Fire cert", m.category === "fabric" ? m.fire_cert || "not published" : null], ["Natural fibre", m.natural_fibre == null ? null : m.natural_fibre ? "yes" : "no"],
      ["Density", m.density_kg_m3 ? m.density_kg_m3 + " kg/m³" : null], ["Hardness", m.hardness_n ? m.hardness_n + " N" : null], ["Thickness", m.thickness_cm ? m.thickness_cm + " cm" : null], ["Sheet", m.sheet_w_cm ? m.sheet_w_cm + " × " + m.sheet_l_cm + " cm" : null]
    ].filter(function (r) { return r[1]; });
    var ims = imagesFor(m.id);
    render('<div class="view-head"><div><a class="btn-link" href="#/materials">← materials</a><h2 style="margin-top:8px">' + esc(m.name) + "</h2>" + '<div class="tags-row">' + seatTag(m) + (m.status !== "active" ? '<span class="tag tag-outline">' + m.status + "</span>" : "") + "</div></div>" +
      '<div><button class="btn btn-secondary" data-act="edit-material">Edit</button> <button class="btn btn-primary" data-act="add-offer" data-id="' + m.id + '">+ Offer</button></div></div>' +
      '<div class="detail-grid"><div>' + imgHtml(m) +
      '<div class="thumbs">' + ims.map(function (im) { return '<div class="fig"><img src="' + esc(API.imageUrl(im.storage_path)) + '" alt="" title="' + esc(im.colourway || "") + '"><button type="button" data-act="del-image" data-id="' + im.id + '" data-path="' + esc(im.storage_path) + '" title="remove">×</button></div>'; }).join("") + "</div>" +
      '<label class="btn btn-secondary btn-small" style="margin-top:12px;display:inline-flex">Upload photo<input type="file" accept="image/*" hidden id="img-upload"></label> <input class="input" id="img-colourway" placeholder="colourway label (optional)" style="width:180px;min-height:32px;padding:4px 0;font-size:13px;margin-left:8px">' +
      '<ul class="spec" style="margin-top:24px">' + spec.map(function (r) { return "<li><span>" + esc(r[0]) + "</span><span>" + esc(r[1]) + "</span></li>"; }).join("") + "</ul>" +
      (m.notes ? '<p class="text-muted" style="font-size:13.5px;line-height:1.6">' + esc(m.notes) + "</p>" : "") + "</div>" +
      "<div><h4>Where to buy</h4><p class=\"text-muted\">★ default · green = cheapest ex VAT · ≈ converted at the fx_rates table.</p>" + offersTable(m.id, true) +
      "</div></div>");
    $("#img-upload").onchange = async function () {
      var file = this.files[0]; if (!file) return;
      try { var path = await API.uploadImage(m.id, file); await API.insert("material_images", { material_id: m.id, storage_path: path, colourway: $("#img-colourway").value || null, position: ims.length, verified: true }); await reload(); route(); toast("Photo uploaded"); }
      catch (e) { toast(e.message, true); }
    };
  }

  function viewSuppliers() {
    setNav("suppliers");
    var rows = S.data.suppliers.map(function (s) {
      var n = S.data.offers.filter(function (o) { return o.supplier_id === s.id; }).length;
      return "<tr><td><a class=\"btn-link\" href=\"#/suppliers/" + s.id + '">' + esc(s.name) + "</a>" + (s.house_id ? ' <span class="tag tag-neutral" style="font-size:9px">house</span>' : "") + "</td>" +
        '<td class="text-muted">' + esc([s.kind, s.trade, s.country].filter(Boolean).join(" · ")) + "</td>" +
        "<td>" + (s.account_status === "open" ? '<span class="tag tag-accent">account open</span>' : s.account_status === "requested" ? '<span class="tag tag-outline">requested</span>' : "") + "</td>" +
        '<td class="text-muted">' + ({ inc_25: "incl. 25 %", inc_20: "incl. 20 %", ex_reverse_charge: "ex VAT", unknown: "?" })[s.vat_treatment || "unknown"] + "</td>" +
        "<td>" + (s.ships_to_sweden === false ? '<span class="note-critical">no</span>' : s.ships_to_sweden ? "yes" : "?") + "</td>" +
        '<td class="num">' + n + '</td><td class="suprating">' + (s.rating ? "★".repeat(s.rating) + "☆".repeat(5 - s.rating) : "") + "</td>" +
        '<td class="supnotes-cell text-muted">' + esc(s.notes || "") + "</td></tr>";
    }).join("");
    render('<div class="view-head"><div><span class="kicker">Where to buy</span><h2>Suppliers</h2></div><div><button class="btn btn-secondary" data-act="new-house">+ House</button> <button class="btn btn-primary" data-act="new-supplier">+ Supplier</button></div></div>' +
      '<div class="tablewrap"><table class="table suptable"><thead><tr><th>Name</th><th>Kind</th><th>Account</th><th>VAT</th><th>Ships SE</th><th class="num">Offers</th><th>Rating</th><th>Notes</th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
      "<h4 style=\"margin-top:48px\">Fabric houses</h4><p class=\"text-muted\">Brands and mills. Prices live on the retailer offers, not here.</p>" +
      '<div class="tablewrap"><table class="table"><thead><tr><th>House</th><th>Country</th><th class="num">Fabrics</th><th>Notes</th><th></th></tr></thead><tbody>' +
      S.data.houses.map(function (h) { var n = S.data.materials.filter(function (m) { return m.house_id === h.id; }).length; return "<tr><td>" + esc(h.name) + (h.website ? ' <a class="btn-link" href="' + esc(h.website) + '" target="_blank" rel="noopener" style="font-size:11px">site</a>' : "") + "</td><td>" + esc(h.country || "") + '</td><td class="num">' + n + '</td><td class="text-muted">' + esc(h.notes || "") + '</td><td><a class="btn-link" href="#" data-act="edit-house" data-id="' + h.id + '">edit</a></td></tr>'; }).join("") + "</tbody></table></div>");
  }

  var RFQ = "Hej,\n\nWe are a Swedish restoration studio reupholstering mid-century furniture. We are choosing our interior material suppliers and would like a quote.\n\nPlease send prices and technical data for:\n1. Kallskum (cold-cure foam) — 3 cm, 4 cm and 5 cm. Please include density in kg/m³, available sheet sizes, and any low-emission certification.\n2. Cotton felt — include weight in g/m².\n3. Wool wadding — include weight in g/m², wool content %, and whether it is laminated or loose fibre.\n4. Calico / scrim — composition and weight in g/m².\n5. Jute webbing — width.\n\nWe would also like: minimum order quantity, lead time, and whether you cut to size.\n\nTack,\nVedda Studio";

  function viewSupplier(id) {
    setNav("suppliers");
    var s = supplier(id); if (!s) return render('<div class="empty">Supplier not found.</div>');
    var os = S.data.offers.filter(function (o) { return o.supplier_id === id; });
    var spec = [["Kind", s.kind], ["Trade", s.trade], ["Country", s.country], ["Website", s.website], ["Email", s.email], ["Phone", s.phone], ["Account", s.account_status], ["VAT on prices", s.vat_treatment], ["Ships to Sweden", s.ships_to_sweden == null ? "not checked" : s.ships_to_sweden ? "yes" : "no"], ["Shipping", s.shipping_note], ["Min order", s.min_order_note], ["House", s.house_id ? (house(s.house_id) || {}).name : null]].filter(function (r) { return r[1]; });
    render('<div class="view-head"><div><a class="btn-link" href="#/suppliers">← suppliers</a><h2 style="margin-top:8px">' + esc(s.name) + "</h2></div><div><button class=\"btn btn-secondary\" data-act=\"copy-rfq\">Copy RFQ email</button> <button class=\"btn btn-primary\" data-act=\"edit-supplier\">Edit</button></div></div>" +
      '<div class="detail-grid"><div><ul class="spec">' + spec.map(function (r) { return "<li><span>" + esc(r[0]) + "</span><span>" + (r[0] === "Website" ? '<a class="btn-link" href="' + esc(r[1]) + '" target="_blank" rel="noopener">' + esc(r[1].replace(/^https?:\/\//, "")) + "</a>" : esc(r[1])) + "</span></li>"; }).join("") + "</ul>" + (s.notes ? '<p class="text-muted" style="font-size:13.5px;line-height:1.6">' + esc(s.notes) + "</p>" : "") + "</div>" +
      "<div><h4>Offers from this supplier (" + os.length + ")</h4>" + (os.length ? '<div class="tablewrap"><table class="table offers-table"><thead><tr><th>Material</th><th class="num">Price</th><th class="num">ex VAT (SEK)</th><th>Unit</th><th>Checked</th><th>Note</th></tr></thead><tbody>' +
        os.map(function (o) { var m = material(o.material_id) || {}, p = offerPrice(o); return '<tr class="' + (o.is_default ? "is-default" : "") + '"><td><a class="btn-link" href="#/materials/' + m.id + '">' + esc(m.name) + '</a></td><td class="num price">' + (o.price == null ? "on request" : num(o.price) + " " + o.currency) + '</td><td class="num price">' + (p.ex == null ? "—" : money(p.ex)) + "</td><td>" + esc(o.unit || "") + "</td><td>" + esc(o.checked || "") + '</td><td class="wrap text-muted">' + esc(o.availability_note || o.notes || "") + "</td></tr>"; }).join("") + "</tbody></table></div>" : '<div class="empty">No offers yet — open a material and add one.</div>') + "</div></div>");
  }

  // ---------------------------------------------------------------- costings
  function recipe(id) { return S.recipes.recipes.filter(function (r) { return r.id === id; })[0] || null; }

  function picksFor(c, lines) {
    // resolve role → {material, offer}: explicit line offer, else the costing's cover, else default offer of a matching material
    var picks = {};
    (lines || []).forEach(function (l) { if (l.role && l.offer_id && !l.is_manual) { var o = byId(S.data.offers, l.offer_id); if (o) picks[l.role] = { material: material(o.material_id), offer: o }; } });
    if (c.cover_offer_id) { var co = byId(S.data.offers, c.cover_offer_id); if (co) picks.cover = { material: material(co.material_id), offer: co }; }
    else if (c.cover_material_id) { var dm = defaultOffer(c.cover_material_id); picks.cover = { material: material(c.cover_material_id), offer: dm }; }
    var r = recipe(c.recipe_id);
    var thick = c.foam_thickness_cm || (r && r.foam && r.foam.thickness_cm);
    ["suspension", "core", "body_wadding", "top_wadding", "liner"].forEach(function (role) {
      if (picks[role]) return;
      var cands = S.data.materials.filter(function (m) { return m.layer_role === role && m.status !== "rejected" && bestOffer(m.id); });
      if (role === "core" && thick) { var exact = cands.filter(function (m) { return Number(m.thickness_cm) === Number(thick); }); if (exact.length) cands = exact; }
      if (cands.length) picks[role] = { material: cands[0], offer: defaultOffer(cands[0].id) };
    });
    return picks;
  }

  function computeCosting(c, lines, picks) {
    var manual = (lines || []).filter(function (l) { return l.is_manual; });
    return CE.compute({ costing: c, recipe: recipe(c.recipe_id), config: S.recipes, picks: picks, manualLines: manual, fx: S.data.fx });
  }

  function checksHtml(res) {
    return '<div class="costchecks">' + res.checks.map(function (k) { return '<span class="' + (k.ok === true ? "note-positive" : k.ok === "warn" ? "warn-line" : k.ok === false ? "note-critical" : "text-muted") + '">' + esc(k.text) + "</span>"; }).join("") + res.warnings.map(function (w) { return '<span class="warn-line">⚠ ' + esc(w) + "</span>"; }).join("") + "</div>";
  }

  function costingCard(c) {
    var lines = linesFor(c.id);
    var snap = c.snapshot || {};
    var frozen = snap.total_cost_ex_vat != null;
    var cover = c.cover_material_id ? material(c.cover_material_id) : null;
    // Checks must be computed from whatever is actually being SHOWN — never
    // re-derive via the recipe engine on top of already-final lines, or a
    // migrated/manual costing's real totals get double-counted with
    // synthetic recipe layers. See costing.js evaluateChecks().
    var shown, totalsForChecks, tInc, tEx;
    if (frozen && lines.length) {
      shown = lines;
      totalsForChecks = { total_cost_ex_vat: snap.total_cost_ex_vat, materials_ex_vat: snap.materials_ex_vat, labour_hours: c.labour_hours };
      tInc = snap.total_cost_inc_vat; tEx = snap.total_cost_ex_vat;
    } else {
      var live = computeCosting(c, lines, picksFor(c, lines));
      shown = live.lines; totalsForChecks = live.totals; tInc = live.totals.total_cost_inc_vat; tEx = live.totals.total_cost_ex_vat;
    }
    var coreIsPu = false; // unknown for frozen cards without re-deriving picks — omit the natural-claim hint there
    var res = { checks: CE.evaluateChecks(c, totalsForChecks, shown, cover, coreIsPu).checks, warnings: [] };
    return '<div class="card costcard">' + (cover ? imgHtml(cover, "ar-landscape") : '<div class="fig ar-landscape"></div>') +
      '<h4 class="card-title-sm">' + esc(c.title) + (c.pieces_in_set > 1 ? ' <span class="text-muted">× ' + c.pieces_in_set + "</span>" : "") + "</h4>" +
      '<div class="text-muted" style="font-size:12px;margin-bottom:8px">' + esc((recipe(c.recipe_id) || {}).name || "manual") + (c.width_cm ? " · " + c.width_cm + "×" + c.depth_cm + " cm" : "") + (frozen ? " · saved " + esc(c.checked || "") : " · live") + "</div>" +
      '<div class="costrows-scroll"><table class="table costtable"><thead><tr><th>Line</th><th>Qty</th><th class="num">Inc.</th><th class="num">Ex.</th></tr></thead><tbody>' +
      shown.map(function (l) { return "<tr><td>" + esc(l.label) + '</td><td class="text-muted">' + (l.qty == null ? "" : num(l.qty) + " " + esc(l.unit || "")) + '</td><td class="num price">' + money(l.price_inc_vat) + '</td><td class="num price">' + money(l.price_ex_vat) + "</td></tr>"; }).join("") + "</tbody></table></div>" +
      '<table class="table costtable costsummary"><tbody><tr class="costsub"><td>Labour — ' + num(c.labour_hours) + "h @ " + money(c.labour_rate) + '</td><td></td><td class="num price">' + money((c.labour_hours || 0) * (c.labour_rate || 0)) + '</td><td class="num price">' + money((c.labour_hours || 0) * (c.labour_rate || 0)) + "</td></tr>" +
      '<tr class="costtotal"><td>Total cost</td><td></td><td class="num price-lg">' + money(tInc) + '</td><td class="num price-lg">' + money(tEx) + "</td></tr></tbody></table>" +
      '<div class="costfoot"><div class="costmeta"><span class="price">Asking ' + money(c.asking_price) + "</span>" + (c.pair_asking_price ? '<span class="text-muted">Set: ' + money(c.pair_asking_price) + "</span>" : "") + "</div>" + checksHtml(res) +
      (c.notes ? '<div class="text-muted costnote">' + esc(c.notes) + "</div>" : "") +
      '<div class="card-actions"><a class="btn-link" href="#/costings/' + c.id + '">open / recalculate</a></div></div></div>';
  }

  function viewCostings() {
    setNav("costings");
    var cs = S.data.costings;
    render('<div class="view-head"><div><span class="kicker">Bill of materials</span><h2>Piece costings</h2><p class="text-muted" style="margin:6px 0 0">Checked against the 50 % markup rule, the 6,000 kr floor, fabric ≤ 25–30 % of sale and kr/hour.</p></div><div><button class="btn btn-primary" data-act="new-costing">+ Costing</button></div></div>' +
      (cs.length ? '<div class="costgrid">' + cs.map(costingCard).join("") + "</div>" : '<div class="empty">No costings yet.</div>'));
    wireCarousels();
  }

  function viewCostingEditor(id) {
    setNav("costings");
    var isNew = id === "new";
    var c = isNew ? { id: null, title: "", recipe_id: "dining-seat", pieces_in_set: 1, labour_rate: S.recipes.defaults.labour_rate, consumables_allowance: S.recipes.defaults.consumables_allowance, status: "draft" } : Object.assign({}, byId(S.data.costings, id));
    if (!isNew && !c.id) return render('<div class="empty">Costing not found.</div>');
    var lines = isNew ? [] : linesFor(id).map(function (l) { return Object.assign({}, l); });
    var manual = lines.filter(function (l) { return l.is_manual; });
    var picks = picksFor(c, lines);
    var covers = S.data.materials.filter(function (m) { return (m.category === "fabric" || m.layer_role === "cover") && m.status !== "rejected"; });

    function layerOptions(role) {
      var cands = S.data.materials.filter(function (m) { return m.layer_role === role && m.status !== "rejected"; });
      var out = [];
      cands.forEach(function (m) { offersFor(m.id).forEach(function (o) { var p = offerPrice(o), s = supplier(o.supplier_id) || {}; out.push([o.id, m.name + " — " + s.name + (p.ex == null ? " (on request)" : " · " + money(p.ex) + " ex " + (o.unit || ""))]); }); });
      return out;
    }
    function pickRow(role, label) {
      var cur = picks[role] && picks[role].offer ? picks[role].offer.id : "";
      return '<div class="layer-pick"><span class="role">' + esc(label) + "</span>" + select("pick_" + role, layerOptions(role), cur, "— none —") + "</div>";
    }

    function formHtml() {
      var r = recipe(c.recipe_id);
      var layers = r ? r.layers : [];
      return '<div class="field"><label>Title</label>' + input("title", c.title, "text", "required") + "</div>" +
        '<div class="two"><div class="field"><label>Recipe</label>' + select("recipe_id", S.recipes.recipes.map(function (x) { return [x.id, x.name]; }), c.recipe_id) + '</div><div class="field"><label>Pieces in set</label>' + select("pieces_in_set", [["1", "1 — single"], ["2", "2 — pair"], ["4", "4"], ["6", "6"]], c.pieces_in_set || 1) + "</div></div>" +
        (r && r.tier_band ? '<p class="text-muted" style="margin:-8px 0 12px;font-size:12.5px">' + esc(r.tier_band) + (r.caveats && r.caveats.length ? " · " + esc(r.caveats.join(" ")) : "") + "</p>" : "") +
        '<div class="two"><div class="field"><label>Seat width cm</label>' + input("width_cm", c.width_cm || (r && r.default_size_cm ? r.default_size_cm.w : ""), "number", 'step="0.5"') + '</div><div class="field"><label>Seat depth cm</label>' + input("depth_cm", c.depth_cm || (r && r.default_size_cm ? r.default_size_cm.d : ""), "number", 'step="0.5"') + "</div></div>" +
        (r && r.back_size_cm ? '<div class="two"><div class="field"><label>Back width cm</label>' + input("back_width_cm", c.back_width_cm || r.back_size_cm.w, "number") + '</div><div class="field"><label>Back depth cm</label>' + input("back_depth_cm", c.back_depth_cm || r.back_size_cm.d, "number") + "</div></div>" : "") +
        (r && !r.no_foam ? '<div class="three"><div class="field"><label>Foam cm</label>' + input("foam_thickness_cm", c.foam_thickness_cm || (r.foam && r.foam.thickness_cm), "number", 'step="0.5"') + '</div><div class="field"><label>Batting tier</label>' + select("batting_tier", Object.keys(S.recipes.batting_tiers).map(function (k) { return [k, k]; }), c.batting_tier || r.batting_tier) + '</div><div class="field"><label>Original foam</label>' + select("keep_original_foam", [["false", "replace"], ["true", "keep (passed tests)"]], String(!!c.keep_original_foam)) + "</div></div>" : "") +
        (layers.indexOf("cover") >= 0 ? '<div class="field"><label>Cover fabric</label>' + select("cover_material_id", covers.map(function (m) { return [m.id, m.name + (CE.seatSuitable(m) === false ? " ⚠ light domestic" : "")]; }), c.cover_material_id, "— pick —") + "</div>" +
          '<div class="two"><div class="field"><label>Cover offer</label>' + select("cover_offer_id", c.cover_material_id ? offersFor(c.cover_material_id).map(function (o) { var p = offerPrice(o); return [o.id, (supplier(o.supplier_id) || {}).name + (p.ex == null ? " (on request)" : " · " + money(p.ex) + " ex")]; }) : [], c.cover_offer_id, "default") + '</div><div class="field"><label>Cover ' + (r && r.cover_unit === "skin" ? "skins" : "metres") + "</label>" + input("cover_metres", c.cover_metres == null ? (r ? r.cover_metres_default : "") : c.cover_metres, "number", 'step="0.05"') + "</div></div>" : "") +
        (layers.length ? '<h4 style="margin-top:16px">Layers — supplier per layer</h4>' + layers.filter(function (l) { return l !== "cover" && l !== "other"; }).map(function (role) { if (role === "top_wadding" && S.recipes.batting_tiers[c.batting_tier || r.batting_tier].layers.indexOf("top_wadding") < 0) return ""; return pickRow(role, ROLE_LABEL[role]); }).join("") : "") +
        '<h4 style="margin-top:16px">Manual lines</h4><p class="text-muted" style="font-size:12px;margin:0 0 8px">Frame, refinishing, brand tag, anything not in the recipe. Sarah\'s real figures go here.</p><div class="manual-lines" id="manual-lines"></div><button type="button" class="btn-link" data-act="add-line" style="font-size:11px">+ line</button>' +
        '<div class="three" style="margin-top:20px"><div class="field"><label>Labour hours (set)</label>' + input("labour_hours", c.labour_hours == null ? (r ? r.labour_hours_default : "") : c.labour_hours, "number", 'step="0.5"') + '</div><div class="field"><label>Rate kr/h</label>' + input("labour_rate", c.labour_rate, "number") + '</div><div class="field"><label>Consumables kr/piece</label>' + input("consumables_allowance", c.consumables_allowance, "number") + "</div></div>" +
        '<div class="three"><div class="field"><label>Asking kr (each)</label>' + input("asking_price", c.asking_price, "number") + '</div><div class="field"><label>Asking kr (set)</label>' + input("pair_asking_price", c.pair_asking_price, "number") + '</div><div class="field"><label>Status</label>' + select("status", ["draft", "active", "done"], c.status) + "</div></div>" +
        '<div class="field"><label>Notes</label>' + textarea("notes", c.notes) + "</div>";
    }

    render('<div class="view-head"><div><a class="btn-link" href="#/costings">← costings</a><h2 style="margin-top:8px">' + (isNew ? "New costing" : esc(c.title)) + "</h2></div>" +
      "<div>" + (isNew ? "" : '<button class="btn btn-secondary" data-act="delete-costing" style="color:var(--color-critical)">Delete</button> ') + '<button class="btn btn-primary" data-act="save-costing">Save & freeze</button></div></div>' +
      '<div class="builder"><form class="form" id="cform" novalidate>' + formHtml() + '</form><div id="result"></div></div>');

    var form = $("#cform");
    function renderManual() {
      $("#manual-lines").innerHTML = manual.map(function (l, i) {
        return '<div class="row" data-i="' + i + '"><input class="input" data-k="label" placeholder="label" value="' + esc(l.label) + '"><input class="input" data-k="qty" placeholder="qty" value="' + esc(l.qty == null ? "" : l.qty) + '"><input class="input" data-k="unit" placeholder="unit" value="' + esc(l.unit || "") + '"><input class="input" data-k="price_inc_vat" placeholder="inc VAT" value="' + esc(l.price_inc_vat == null ? "" : l.price_inc_vat) + '"><input class="input" data-k="price_ex_vat" placeholder="ex VAT" value="' + esc(l.price_ex_vat == null ? "" : l.price_ex_vat) + '"><button type="button" class="del" title="remove">×</button></div>';
      }).join("");
      $$("#manual-lines .row").forEach(function (row) {
        var i = Number(row.getAttribute("data-i"));
        row.oninput = function (e) { var k = e.target.getAttribute("data-k"); var v = e.target.value; manual[i][k] = (k === "label" || k === "unit") ? v : (v === "" ? null : Number(v.replace(",", "."))); if (k === "price_inc_vat" && manual[i].price_ex_vat == null) { /* leave ex empty → treated as = inc */ } recompute(); };
        $(".del", row).onclick = function () { manual.splice(i, 1); renderManual(); recompute(); };
      });
    }
    function readForm() {
      ["title", "recipe_id", "notes", "status", "cover_material_id", "cover_offer_id", "batting_tier"].forEach(function (k) { if (form.elements[k]) c[k] = val(form, k); });
      ["pieces_in_set", "width_cm", "depth_cm", "back_width_cm", "back_depth_cm", "foam_thickness_cm", "cover_metres", "labour_hours", "labour_rate", "consumables_allowance", "asking_price", "pair_asking_price"].forEach(function (k) { if (form.elements[k]) c[k] = numv(form, k); });
      if (form.elements.keep_original_foam) c.keep_original_foam = val(form, "keep_original_foam") === "true";
      picks = {};
      ["suspension", "core", "body_wadding", "top_wadding", "liner"].forEach(function (role) { var el = form.elements["pick_" + role]; if (el && el.value) { var o = byId(S.data.offers, el.value); if (o) picks[role] = { material: material(o.material_id), offer: o }; } });
      if (c.cover_material_id) { var o2 = c.cover_offer_id ? byId(S.data.offers, c.cover_offer_id) : defaultOffer(c.cover_material_id); picks.cover = { material: material(c.cover_material_id), offer: o2 }; }
    }
    var last;
    function recompute() {
      readForm();
      last = CE.compute({ costing: c, recipe: recipe(c.recipe_id), config: S.recipes, picks: picks, manualLines: manual, fx: S.data.fx });
      var t = last.totals;
      $("#result").innerHTML = '<div class="sticky-totals"><div><span class="kicker">Materials ex VAT</span><span class="price-lg">' + money(t.materials_ex_vat) + '</span></div><div><span class="kicker">Labour</span><span class="price-lg">' + money(t.labour_cost) + '</span></div><div><span class="kicker">Total ex VAT</span><span class="price-lg">' + money(t.total_cost_ex_vat) + '</span></div><div><span class="kicker">Total inc VAT</span><span class="price-lg">' + money(t.total_cost_inc_vat) + "</span></div></div>" +
        '<p class="text-muted" style="font-size:12.5px">Padded area ' + num(t.padded_area_m2) + " m² (incl. wrap allowance)" + (t.pieces_in_set > 1 ? " · quantities are for the set of " + t.pieces_in_set : "") + (t.lines_missing_price ? ' · <span class="note-critical">' + t.lines_missing_price + " line(s) without a price</span>" : "") + "</p>" +
        '<table class="table result-table"><thead><tr><th>Line</th><th>Qty</th><th class="num">Unit ex</th><th class="num">Inc VAT</th><th class="num">Ex VAT</th></tr></thead><tbody>' +
        last.lines.map(function (l) { return '<tr class="' + (l.missing ? "missing" : l.approx ? "approx" : "") + '"><td>' + esc(l.label) + (l.note ? '<span class="sub">' + esc(l.note) + "</span>" : "") + '</td><td class="text-muted">' + (l.qty == null ? "" : num(l.qty) + " " + esc(l.unit || "")) + '</td><td class="num price">' + (l.unit_price_ex == null ? "" : num(l.unit_price_ex, 0)) + '</td><td class="num price">' + money(l.price_inc_vat) + '</td><td class="num price">' + money(l.price_ex_vat) + "</td></tr>"; }).join("") + "</tbody></table>" +
        checksHtml(last);
    }
    form.oninput = function (e) {
      if (e.target.name === "recipe_id" || e.target.name === "cover_material_id" || e.target.name === "batting_tier") { readForm(); if (e.target.name === "recipe_id") { var r = recipe(c.recipe_id); c.width_cm = null; c.depth_cm = null; c.back_width_cm = null; c.back_depth_cm = null; c.foam_thickness_cm = null; c.batting_tier = null; c.cover_metres = null; c.labour_hours = null; } if (e.target.name === "cover_material_id") c.cover_offer_id = null; picks = picksFor(c, []); form.innerHTML = formHtml(); renderManual(); }
      recompute();
    };
    form.onchange = form.oninput;
    $('[data-act="add-line"]').onclick = function () { manual.push({ label: "", qty: 1, unit: "piece", price_inc_vat: null, price_ex_vat: null, is_manual: true, role: "other" }); renderManual(); recompute(); };
    renderManual(); recompute();
    $$("#manual-lines").forEach(function (ml) { ml.addEventListener("click", function (e) { if (e.target.getAttribute("data-act") === "add-line") $('[data-act="add-line"]').onclick(); }); });

    $('[data-act="save-costing"]').onclick = async function () {
      recompute();
      if (!c.title) return toast("Title is required", true);
      var row = {
        id: c.id || API.nextId("pcost", S.data.costings), piece_id: c.piece_id || null, title: c.title, recipe_id: c.recipe_id, width_cm: c.width_cm, depth_cm: c.depth_cm, back_width_cm: c.back_width_cm, back_depth_cm: c.back_depth_cm,
        pieces_in_set: c.pieces_in_set || 1, foam_thickness_cm: c.foam_thickness_cm, batting_tier: c.batting_tier, keep_original_foam: !!c.keep_original_foam, cover_material_id: c.cover_material_id, cover_offer_id: c.cover_offer_id, cover_metres: c.cover_metres,
        labour_hours: c.labour_hours, labour_rate: c.labour_rate, consumables_allowance: c.consumables_allowance, asking_price: c.asking_price, pair_asking_price: c.pair_asking_price, status: c.status || "draft", notes: c.notes, checked: today(),
        snapshot: { source: "app", computed_at: new Date().toISOString(), materials_inc_vat: last.totals.materials_inc_vat, materials_ex_vat: last.totals.materials_ex_vat, labour_cost: last.totals.labour_cost, total_cost_inc_vat: last.totals.total_cost_inc_vat, total_cost_ex_vat: last.totals.total_cost_ex_vat, padded_area_m2: last.totals.padded_area_m2, checks: last.checks }
      };
      try {
        await API.upsert("costings", row);
        await API.replaceLines(row.id, last.lines.map(function (l) { return { role: l.role, label: l.label, material_id: l.material_id, offer_id: l.offer_id, qty: l.qty, unit: l.unit, price_inc_vat: l.price_inc_vat, price_ex_vat: l.price_ex_vat, is_manual: l.is_manual, note: l.note }; }));
        await reload(); location.hash = "#/costings"; toast("Costing saved");
      } catch (e) { toast(e.message, true); }
    };
    if (!isNew) $('[data-act="delete-costing"]').onclick = function () {
      confirmDialog("Delete this costing?", async function () { await API.remove("costings", c.id); await reload(); location.hash = "#/costings"; });
    };
  }

  // ---------------------------------------------------------------- router / shell
  function render(html) { var v = $("#view"); v.innerHTML = html; wireCarousels(v); window.scrollTo(0, 0); }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    var openCard = e.target.closest && e.target.closest("[data-open]");
    if (openCard) location.hash = openCard.getAttribute("data-open");
  });
  document.addEventListener("click", function (e) {
    var openCard = e.target.closest("[data-open]");
    if (openCard && !e.target.closest("a,button")) { location.hash = openCard.getAttribute("data-open"); return; }
    var a = e.target.closest("[data-act]"); if (!a || a.closest("#dialog-root")) return;
    var act = a.getAttribute("data-act"), id = a.getAttribute("data-id");
    var handled = true;
    switch (act) {
      case "new-material": materialForm(null, (S.filters.materials || {}).category || "interior"); break;
      case "edit-material": materialForm(material(location.hash.split("/")[2])); break;
      case "add-offer": offerForm(id); break;
      case "edit-offer": offerForm(byId(S.data.offers, id).material_id, byId(S.data.offers, id)); break;
      case "new-supplier": supplierForm(null); break;
      case "edit-supplier": supplierForm(supplier(location.hash.split("/")[2])); break;
      case "new-house": houseForm(null); break;
      case "edit-house": houseForm(house(id)); break;
      case "new-costing": location.hash = "#/costings/new"; break;
      case "copy-rfq": navigator.clipboard.writeText(RFQ).then(function () { toast("RFQ copied"); }); break;
      case "del-image": confirmDialog("Remove this photo?", function () { return API.deleteImage(a.getAttribute("data-path")).catch(function () {}).then(function () { return API.remove("material_images", Number(id)); }).then(reload).then(route); }); break;
      default: handled = false;
    }
    if (handled) e.preventDefault();
  });

  function route() {
    if (!S.user || !S.data) return;
    var parts = location.hash.replace(/^#\/?/, "").split("/");
    var p = parts[0] || "materials", id = parts[1];
    if (p === "materials" && id) viewMaterial(id);
    else if (p === "materials") viewMaterials();
    else if (p === "suppliers" && id) viewSupplier(id);
    else if (p === "suppliers") viewSuppliers();
    else if (p === "costings" && id) viewCostingEditor(id);
    else if (p === "costings") viewCostings();
    else viewMaterials();
  }
  window.addEventListener("hashchange", route);

  var booting = false;
  async function boot(session) {
    var uid = session ? session.user.id : null;
    if (uid && S.user && S.user.id === uid && S.data) return; // already booted for this user
    S.user = session ? session.user : null;
    $("#login").hidden = !!S.user; $("#view").hidden = !S.user;
    $("#nav-user").hidden = !S.user; $("#nav-signout").hidden = !S.user;
    if (!S.user) { S.data = null; return; }
    $("#nav-user").textContent = S.user.email;
    if (booting) return;
    booting = true;
    try {
      if (!S.recipes) S.recipes = await fetch("recipes.json").then(function (r) { return r.json(); });
      S.data = await API.loadAll();
      route();
    } catch (e) { render('<div class="empty note-critical">Could not load data: ' + esc(e.message) + "</div>"); }
    finally { booting = false; }
  }

  $("#login-form").onsubmit = async function (e) {
    e.preventDefault();
    var f = e.target, err = $("#login-error"); err.hidden = true;
    try { await API.signIn(f.email.value.trim(), f.password.value); }
    catch (ex) { err.textContent = ex.message || "Sign-in failed"; err.hidden = false; }
  };
  $("#nav-signout").onclick = function () { API.signOut(); };
  API.onAuth(boot);
  API.session().then(boot);
})();
