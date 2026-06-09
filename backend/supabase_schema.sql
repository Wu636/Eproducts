-- Supabase schema for the XHS ecommerce asset generator.
-- Run this once in Supabase SQL Editor before enabling XHS_STORAGE_BACKEND=supabase.

create table if not exists public.products (
  id text primary key,
  name text not null,
  category text not null default '其他',
  price text not null default '',
  audience text not null default '',
  selling_points jsonb not null default '[]'::jsonb,
  scene text not null default '',
  tone text not null default '真实种草',
  spec text not null default '',
  forbidden_words jsonb not null default '[]'::jsonb,
  product_url text not null default '',
  image_url text not null default '',
  variants jsonb not null default '[]'::jsonb,
  selected_variant_id text not null default '',
  created_at text not null default (current_date::text),
  updated_at text not null default (current_date::text)
);

create table if not exists public.assets (
  id text primary key,
  product_id text not null default '',
  product_name text not null default '',
  type text not null default 'copy',
  title text not null default '',
  status text not null default 'review',
  style text not null default '',
  content text not null default '',
  url text not null default '',
  provider_task jsonb not null default '{}'::jsonb,
  provider_status text not null default '',
  variant_id text not null default '',
  variant_name text not null default '',
  source_image_url text not null default '',
  generation_plan jsonb not null default '{}'::jsonb,
  created_at text not null default (current_date::text)
);

create table if not exists public.note_packages (
  id text primary key,
  product_id text not null default '',
  product_name text not null default '',
  title text not null default '',
  angle text not null default '',
  persona text not null default '',
  status text not null default 'review',
  score integer not null default 80,
  copy_asset_id text not null default '',
  cover_asset_id text not null default '',
  detail_asset_ids jsonb not null default '[]'::jsonb,
  video_asset_id text not null default '',
  summary text not null default '',
  hashtags jsonb not null default '[]'::jsonb,
  publish_plan text not null default '待排期',
  goal text not null default '引流成交',
  created_at text not null default (current_date::text)
);

create table if not exists public.generation_jobs (
  id text primary key,
  product_id text not null default '',
  product_name text not null default '',
  type text not null default 'note_package',
  title text not null default '',
  status text not null default 'running',
  progress integer not null default 0,
  detail text not null default '',
  config jsonb not null default '{}'::jsonb,
  result jsonb not null default '{}'::jsonb,
  created_at text not null default (current_date::text)
);

create table if not exists public.uploads (
  id text primary key,
  filename text not null default '',
  content_type text not null default '',
  url text not null default '',
  created_at text not null default (current_date::text)
);

create table if not exists public.template_prompts (
  id text primary key,
  type text not null,
  template_id text not null,
  prompt text not null default '',
  updated_at text not null default (current_date::text),
  unique (type, template_id)
);

create index if not exists idx_products_updated_at on public.products (updated_at desc);
create index if not exists idx_assets_product_id on public.assets (product_id);
create index if not exists idx_assets_type on public.assets (type);
create index if not exists idx_assets_status on public.assets (status);
create index if not exists idx_note_packages_product_id on public.note_packages (product_id);
create index if not exists idx_generation_jobs_status on public.generation_jobs (status);

alter table public.products enable row level security;
alter table public.assets enable row level security;
alter table public.note_packages enable row level security;
alter table public.generation_jobs enable row level security;
alter table public.uploads enable row level security;
alter table public.template_prompts enable row level security;

insert into storage.buckets (id, name, public)
values ('xhs-assets', 'xhs-assets', true)
on conflict (id) do update set public = excluded.public;

do $$
begin
  if not exists (
    select 1
    from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and policyname = 'Public read xhs assets'
  ) then
    create policy "Public read xhs assets"
    on storage.objects for select
    using (bucket_id = 'xhs-assets');
  end if;
end $$;
