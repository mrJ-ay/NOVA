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

-- Likes and comments used by NOVA's public API (the backend accesses these with its secret key).
alter table public.videos
add column if not exists like_count integer not null default 0;

create table if not exists public.nova_video_likes (
    video_id uuid not null references public.videos(id) on delete cascade,
    user_id uuid not null references public.nova_users(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (video_id, user_id)
);

create table if not exists public.nova_comments (
    id uuid primary key default gen_random_uuid(),
    video_id uuid not null references public.videos(id) on delete cascade,
    user_id uuid references public.nova_users(id) on delete set null,
    nickname text not null,
    content text not null check (char_length(content) between 1 and 1000),
    created_at timestamptz not null default now()
);

alter table public.nova_video_likes enable row level security;
alter table public.nova_comments enable row level security;
revoke all on public.nova_video_likes, public.nova_comments from anon, authenticated;
grant all on public.nova_video_likes, public.nova_comments to service_role;

create or replace function public.nova_update_video_like_count()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    if (tg_op = 'INSERT') then
        update public.videos set like_count = like_count + 1 where id = new.video_id;
        return new;
    elsif (tg_op = 'DELETE') then
        update public.videos set like_count = greatest(like_count - 1, 0) where id = old.video_id;
        return old;
    end if;
    return null;
end;
$$;

drop trigger if exists nova_video_like_count_trigger on public.nova_video_likes;
create trigger nova_video_like_count_trigger
after insert or delete on public.nova_video_likes
for each row execute function public.nova_update_video_like_count();

update public.videos v
set like_count = (select count(*) from public.nova_video_likes l where l.video_id = v.id);
