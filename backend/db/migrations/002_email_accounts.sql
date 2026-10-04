-- Browser accounts are separate from trusted adapter identities and planner roles.
create table auth_accounts (
  user_id integer primary key references users(id) on delete cascade,
  email text not null unique check (email = lower(trim(email)) and length(email) between 3 and 254),
  password_hash text not null,
  role text not null check (role in ('rider', 'owner', 'buyer')),
  created_at timestamptz not null default now()
);

create table auth_sessions (
  token_hash text primary key,
  user_id integer not null references auth_accounts(user_id) on delete cascade,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index auth_sessions_user_idx on auth_sessions(user_id);
create index auth_sessions_expiry_idx on auth_sessions(expires_at);

-- Atomic counters survive application restarts and work across server workers.
create table auth_rate_limits (
  key text primary key,
  started_at timestamptz not null default now(),
  attempts integer not null default 1
);
