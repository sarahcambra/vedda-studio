-- Vedda Studio sourcing scanner — shared state + display copy.
-- scanner.db (local SQLite) is still what the scanner writes to directly;
-- a sync step (tools/scanner/sync_supabase.py) pushes rows here after each
-- run. This table is what both dashboards (private + public) read from,
-- and what you/Amanda write to (love/discard/bought/notes) from the page.
-- Run once in Supabase's SQL Editor (Project > SQL Editor > New query).

create table if not exists lots (
  lot_key text primary key,        -- "{source}-{lot_id}", or "manual-<uuid>" for self-added lots

  -- scraped / synced from scanner.db — sync overwrites these, don't hand-edit
  source text not null,             -- auctionet / tradera / bukowskis / haraldssons / manual
  lot_id text,
  url text,
  title text,
  description text,
  category text,
  current_bid numeric,
  final_bid numeric,                -- filled in by a future post-auction re-check, not yet built
  estimate_low numeric,
  estimate_high numeric,
  ends_at timestamptz,
  status text default 'active',     -- active / ended_unsold / sold
  bid_count integer,
  location text,
  currency text default 'SEK',
  image_url text,
  matched_keyword text,
  matched_kind text,
  bad_listing_score numeric,
  price_score numeric,
  first_seen timestamptz default now(),
  last_seen timestamptz default now(),

  -- dashboard-editable — sync never touches these once set
  state text default 'new' check (state in ('new', 'loved', 'discarded', 'bought')),
  discard_reason text,
  bought_price numeric,
  bought_date date,
  delivery_price numeric,
  delivery_price_estimated numeric,
  notes text,

  updated_at timestamptz not null default now()
);

create index if not exists idx_lots_state on lots(state);
create index if not exists idx_lots_ends_at on lots(ends_at);

-- Full image gallery, populated only when a lot is marked bought
-- (search-results APIs only ever give one thumbnail; the rest needs a
-- one-time per-item detail-page fetch, triggered at purchase time).
create table if not exists lot_images (
  id bigint generated always as identity primary key,
  lot_key text not null references lots(lot_key) on delete cascade,
  image_url text not null,
  position integer default 0
);

create index if not exists idx_lot_images_lot_key on lot_images(lot_key);

alter table lots enable row level security;
alter table lot_images enable row level security;

-- Fine to leave fully open here — this table holds no supplier pricing,
-- costing, or buy-strategy data, only public auction-listing info plus
-- your own love/discard/purchase notes. The anon key is meant to be public.
create policy "anyone can read lots" on lots for select using (true);
create policy "anyone can insert lots" on lots for insert with check (true);
create policy "anyone can update lots" on lots for update using (true);
create policy "anyone can delete lots" on lots for delete using (true);

create policy "anyone can read lot_images" on lot_images for select using (true);
create policy "anyone can insert lot_images" on lot_images for insert with check (true);
create policy "anyone can update lot_images" on lot_images for update using (true);
create policy "anyone can delete lot_images" on lot_images for delete using (true);
