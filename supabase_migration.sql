-- Run this in Supabase Dashboard > SQL Editor before deploying the nickname-only account system.
alter table public.videos
add column if not exists uploader_name text not null default 'NOVA';

create table if not exists public.nova_users (
    id uuid primary key default gen_random_uuid(),
    nickname text not null,
    nickname_key text not null unique,
    password_hash text not null,
    is_admin boolean not null default false,
    created_at timestamptz not null default now()
);

alter table public.nova_users enable row level security;
revoke all on public.nova_users from anon, authenticated;
grant all on public.nova_users to service_role;

alter table public.videos
add column if not exists owner_id uuid references public.nova_users(id) on delete set null;

alter table public.videos alter column user_id drop not null;
