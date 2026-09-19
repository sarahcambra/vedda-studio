/* Supabase access for the private app. Anon key is public by design; every
 * table here is RLS-locked to authenticated users, so nothing is readable
 * without a session. */
(function () {
  "use strict";
  var SUPABASE_URL = "https://rnquevahynifwpyynrbd.supabase.co";
  var SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJucXVldmFoeW5pZndweXlucmJkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk2MDQ5NDIsImV4cCI6MjEwNTE4MDk0Mn0.2xIZMYpxk-c6_xt7x8J0EkzRMWyRRRu4gy4kIEtLy1U";
  var BUCKET = "materials";

  var sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

  function must(res) {
    if (res.error) throw res.error;
    return res.data;
  }

  var api = {
    client: sb,

    // ---- auth
    session: function () { return sb.auth.getSession().then(function (r) { return r.data.session; }); },
    signIn: function (email, password) { return sb.auth.signInWithPassword({ email: email, password: password }).then(must); },
    signOut: function () { return sb.auth.signOut(); },
    onAuth: function (cb) { sb.auth.onAuthStateChange(function (_e, s) { cb(s); }); },

    // ---- bulk load (the whole catalogue is small — hundreds of rows at most)
    loadAll: function () {
      return Promise.all([
        sb.from("houses").select("*").order("name"),
        sb.from("suppliers").select("*").order("name"),
        sb.from("materials").select("*").order("name"),
        sb.from("material_offers").select("*"),
        sb.from("material_images").select("*").order("position"),
        sb.from("fx_rates").select("*"),
        sb.from("costings").select("*").order("id"),
        sb.from("costing_lines").select("*").order("position"),
      ]).then(function (r) {
        var d = r.map(must);
        var fx = {};
        d[5].forEach(function (f) { fx[f.currency] = f; });
        return { houses: d[0], suppliers: d[1], materials: d[2], offers: d[3], images: d[4], fx: fx, costings: d[6], lines: d[7] };
      });
    },

    // ---- writes
    upsert: function (table, row) { return sb.from(table).upsert(row).select().then(must); },
    insert: function (table, row) { return sb.from(table).insert(row).select().then(must); },
    update: function (table, id, patch) { return sb.from(table).update(patch).eq("id", id).select().then(must); },
    remove: function (table, id) { return sb.from(table).delete().eq("id", id).then(must); },
    replaceLines: function (costingId, lines) {
      return sb.from("costing_lines").delete().eq("costing_id", costingId).then(must).then(function () {
        if (!lines.length) return [];
        return sb.from("costing_lines").insert(lines.map(function (l, i) {
          return {
            costing_id: costingId, position: i, role: l.role, label: l.label,
            material_id: l.material_id || null, offer_id: l.offer_id || null,
            qty: l.qty, unit: l.unit, price_inc_vat: l.price_inc_vat, price_ex_vat: l.price_ex_vat,
            is_manual: !!l.is_manual, qty_pinned: !!l.qty_pinned, note: l.note || null
          };
        })).select().then(must);
      });
    },

    // ---- images
    uploadImage: function (materialId, file) {
      var slug = file.name.toLowerCase().replace(/[^a-z0-9.]+/g, "-");
      var path = materialId + "/" + slug;
      return sb.storage.from(BUCKET).upload(path, file, { upsert: true }).then(must).then(function () { return path; });
    },
    imageUrl: function (path) { return sb.storage.from(BUCKET).getPublicUrl(path).data.publicUrl; },
    deleteImage: function (path) { return sb.storage.from(BUCKET).remove([path]).then(must); },

    // ---- ids: "m-021" style, next after the highest existing
    nextId: function (prefix, rows) {
      var max = 0;
      rows.forEach(function (r) {
        var m = String(r.id || "").match(new RegExp("^" + prefix + "-(\\d+)$"));
        if (m) max = Math.max(max, parseInt(m[1], 10));
      });
      var n = String(max + 1);
      while (n.length < 3) n = "0" + n;
      return prefix + "-" + n;
    },
    slugId: function (prefix, name, rows) {
      var base = prefix + "-" + name.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
      var id = base, i = 2;
      var ids = {};
      rows.forEach(function (r) { ids[r.id] = 1; });
      while (ids[id]) id = base + "-" + (i++);
      return id;
    }
  };

  window.VeddaApi = api;
})();
