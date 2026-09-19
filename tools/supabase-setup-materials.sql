-- Vedda Studio — materials / suppliers / offers / costings.
-- Additive to tools/supabase-setup.sql (lots). Run once in Supabase SQL Editor.
--
-- Access model: everything here is PRIVATE. Only logged-in users (Sarah, Amanda)
-- can read or write; the anon key used by the public sourcing page gets nothing.
-- Prices and costings never reach the public site — enforced by RLS, not by
-- hiding the page.

-- ---------------------------------------------------------------- helpers
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ---------------------------------------------------------------- houses
-- Fabric brands / mills (Casamance, Manuel Canovas, Kvadrat…). Not where you
-- buy — that's a supplier. A house that also sells direct has a supplier row
-- pointing back here via suppliers.house_id.
create table if not exists houses (
  id text primary key,                 -- "h-casamance"
  name text not null,
  country text,
  website text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- suppliers
create table if not exists suppliers (
  id text primary key,                 -- keeps existing "s-foam-mobelbiten" ids
  name text not null,
  kind text,                           -- textile_supplier / dealer / auction / service
  trade text,                          -- "foam and interior materials"
  country text,
  website text,
  phone text,
  email text,
  rating integer check (rating between 1 and 5),
  house_id text references houses(id) on delete set null,
  account_status text not null default 'none'
    check (account_status in ('none', 'requested', 'open')),
  vat_treatment text not null default 'unknown'
    check (vat_treatment in ('inc_25', 'inc_20', 'ex_reverse_charge', 'unknown')),
  ships_to_sweden boolean,
  shipping_note text,
  min_order_note text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------- materials
-- The generic thing. No price here — prices live on material_offers.
create table if not exists materials (
  id text primary key,                 -- keeps existing "m-001" ids
  name text not null,
  category text not null check (category in ('fabric', 'interior', 'consumable', 'equipment')),
  subcategory text,
  status text not null default 'active' check (status in ('active', 'watch', 'rejected')),
  unit_kind text not null default 'piece'
    check (unit_kind in ('length_m', 'sheet', 'piece', 'pack', 'can', 'spool')),
  layer_role text
    check (layer_role in ('suspension', 'core', 'body_wadding', 'top_wadding', 'liner',
                          'adhesive', 'cover', 'other')),
  composition text,
  width_cm numeric,
  weight_gsm numeric,
  martindale integer,
  -- fabric
  house_id text references houses(id) on delete set null,
  collection text,
  pattern text,
  colourway text,
  tier text check (tier in ('pattern', 'quality', 'sheepskin')),
  fabric_type text check (fabric_type in ('pattern', 'wool', 'boucle', 'corduroy', 'mohair',
                                          'linen', 'velvet', 'leather', 'sheepskin', 'other')),
  repeat_cm numeric,
  fire_cert text,
  natural_fibre boolean,
  -- interior / foam
  density_kg_m3 numeric,
  hardness_n numeric,
  thickness_cm numeric,
  sheet_w_cm numeric,
  sheet_l_cm numeric,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_materials_category on materials(category);
create index if not exists idx_materials_layer_role on materials(layer_role);
create index if not exists idx_materials_house on materials(house_id);

-- ---------------------------------------------------------------- material_offers
-- One row per place you can buy a material. This is the many-to-many.
create table if not exists material_offers (
  id text primary key,                 -- "mo-001"
  material_id text not null references materials(id) on delete cascade,
  supplier_id text not null references suppliers(id) on delete restrict,
  price numeric,                       -- null = "on request" / not yet quoted
  currency text not null default 'SEK' check (currency in ('SEK', 'EUR', 'GBP', 'USD', 'NOK', 'DKK')),
  unit text not null default 'per m',  -- "per m", "per 120x200cm sheet", "per piece"…
  vat_included boolean not null default true,
  vat_rate numeric not null default 0.25,
  price_ex_vat_override numeric,       -- Sarah's real invoiced figure beats the formula
  width_cm numeric,                    -- offer-specific width if it differs from the material
  min_order text,
  lead_time text,
  availability_note text,              -- "kan endast köpas med en säljplan", "slutsåld"
  source_url text,
  checked date,
  is_default boolean not null default false,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_offers_material on material_offers(material_id);
create index if not exists idx_offers_supplier on material_offers(supplier_id);

-- ---------------------------------------------------------------- material_images
create table if not exists material_images (
  id bigint generated always as identity primary key,
  material_id text not null references materials(id) on delete cascade,
  storage_path text not null,          -- "m-001/coordonne-edinburgh-vibrant-indigo.jpg" in bucket "materials"
  colourway text,
  position integer not null default 0,
  verified boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists idx_images_material on material_images(material_id);

-- ---------------------------------------------------------------- fx_rates
create table if not exists fx_rates (
  currency text primary key,
  rate_to_sek numeric not null,
  checked date,
  note text
);
insert into fx_rates (currency, rate_to_sek, checked, note) values
  ('SEK', 1, current_date, 'base'),
  ('EUR', 11.5, current_date, 'research/material-suppliers.md §4 approximation — update from a real rate')
on conflict (currency) do nothing;

-- ---------------------------------------------------------------- costings
create table if not exists costings (
  id text primary key,                 -- keeps "pcost-001"
  piece_id text,                       -- still a pieces.json id for now
  title text not null,
  recipe_id text,                      -- key into docs/app/recipes.json; null = manual
  width_cm numeric,
  depth_cm numeric,
  back_width_cm numeric,
  back_depth_cm numeric,
  pieces_in_set integer not null default 1,
  foam_thickness_cm numeric,
  batting_tier text check (batting_tier in ('thin', 'medium', 'full')),
  keep_original_foam boolean not null default false,
  cover_material_id text references materials(id) on delete set null,
  cover_offer_id text references material_offers(id) on delete set null,
  cover_metres numeric,
  labour_hours numeric,
  labour_rate numeric not null default 500,
  consumables_allowance numeric not null default 100,
  asking_price numeric,
  pair_asking_price numeric,
  status text not null default 'draft' check (status in ('draft', 'active', 'done')),
  notes text,
  checked date,
  snapshot jsonb,                      -- computed lines + totals at last save
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists costing_lines (
  id bigint generated always as identity primary key,
  costing_id text not null references costings(id) on delete cascade,
  position integer not null default 0,
  role text,                           -- suspension / core / … / cover / frame / consumables / brand_tag / other
  label text not null,
  material_id text references materials(id) on delete set null,
  offer_id text references material_offers(id) on delete set null,
  qty numeric,
  unit text,
  price_inc_vat numeric,
  price_ex_vat numeric,
  is_manual boolean not null default true,   -- true = keep as typed; false = regenerated on recalc
  qty_pinned boolean not null default false,
  note text
);
create index if not exists idx_costing_lines_costing on costing_lines(costing_id);

-- ---------------------------------------------------------------- updated_at triggers
do $$
declare t text;
begin
  foreach t in array array['houses','suppliers','materials','material_offers','costings'] loop
    execute format('drop trigger if exists trg_%1$s_updated on %1$s', t);
    execute format('create trigger trg_%1$s_updated before update on %1$s
                    for each row execute function set_updated_at()', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- RLS: authenticated only
do $$
declare t text;
begin
  foreach t in array array['houses','suppliers','materials','material_offers',
                           'material_images','fx_rates','costings','costing_lines'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "auth read %1$s" on %1$I', t);
    execute format('drop policy if exists "auth write %1$s" on %1$I', t);
    execute format('create policy "auth read %1$s" on %1$I for select to authenticated using (true)', t);
    execute format('create policy "auth write %1$s" on %1$I for all to authenticated using (true) with check (true)', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- storage bucket
-- Swatch photos: public read (not sensitive), authenticated write.
insert into storage.buckets (id, name, public)
values ('materials', 'materials', true)
on conflict (id) do nothing;

drop policy if exists "materials public read" on storage.objects;
drop policy if exists "materials auth write" on storage.objects;
drop policy if exists "materials auth update" on storage.objects;
drop policy if exists "materials auth delete" on storage.objects;

create policy "materials public read" on storage.objects
  for select using (bucket_id = 'materials');
create policy "materials auth write" on storage.objects
  for insert to authenticated with check (bucket_id = 'materials');
create policy "materials auth update" on storage.objects
  for update to authenticated using (bucket_id = 'materials');
create policy "materials auth delete" on storage.objects
  for delete to authenticated using (bucket_id = 'materials');
