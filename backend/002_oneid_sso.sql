-- Map existing NOVA Supabase Auth accounts to ONEID without changing current video ownership.
create table if not exists public.oneid_links (
    oneid_user_id uuid primary key,
    legacy_supabase_user_id uuid unique references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);
alter table public.oneid_links enable row level security;
revoke all on public.oneid_links from public, anon, authenticated;
grant all on public.oneid_links to service_role;

-- New NOVA profiles use their stable ONEID UUID. Existing video owner UUIDs remain untouched.
alter table public.videos drop constraint if exists videos_user_id_fkey;

notify pgrst, 'reload schema';
