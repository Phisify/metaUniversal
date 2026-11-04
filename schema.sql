-- Run once in the Supabase SQL editor.

create table if not exists posts (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  story_url    text not null,
  story_title  text not null,
  source       text,
  pillar       text,
  status       text not null check (status in ('posted','rejected','dry_run','failed')),
  reason       text,
  ig_media_id  text,
  payload      jsonb
);
create index if not exists posts_created_idx on posts (created_at desc);
create index if not exists posts_url_idx on posts (story_url);

create table if not exists settings (
  key         text primary key,
  value       text not null,
  updated_at  timestamptz not null default now()
);

-- Service-role key only. No public access to the token or the log.
alter table posts enable row level security;
alter table settings enable row level security;

-- Public bucket for slide images (Instagram fetches them by URL).
insert into storage.buckets (id, name, public)
values ('meta-engine', 'meta-engine', true)
on conflict (id) do nothing;
