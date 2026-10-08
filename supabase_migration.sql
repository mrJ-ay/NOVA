-- Run this once in Supabase Dashboard > SQL Editor before deploying nickname support.
alter table public.videos
add column if not exists uploader_name text not null default 'NOVA';
