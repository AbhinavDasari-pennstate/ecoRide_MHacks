-- Campus trip-sharing schema. Plain SQL, idempotent (safe to re-run).
-- Money is integer cents. Times are timestamptz (UTC).

create table if not exists users (
  id        serial primary key,
  name      text not null unique,
  phone     text,                                  -- fake numbers only
  roles     text[] not null default '{}',          -- driver | passenger | owner
  home_lat  double precision not null,
  home_lng  double precision not null,
  verified  boolean not null default false,        -- mock
  rating    numeric(2,1)                           -- mock
);

create table if not exists vehicles (
  id                   serial primary key,
  owner_id             int references users(id),
  make_model           text not null,
  fuel_type            text not null check (fuel_type in ('ev', 'gas')),
  seats                int not null check (seats > 0),       -- total occupants incl. driver
  range_mi             double precision not null,
  efficiency           double precision not null,            -- kWh per mile (ev) or mpg (gas)
  price_per_hour_cents int not null check (price_per_hour_cents >= 0),
  lat                  double precision not null,
  lng                  double precision not null,
  avail_start          timestamptz not null,
  avail_end            timestamptz not null,
  active               boolean not null default true
);

create table if not exists trips (
  id             serial primary key,
  user_id        int not null references users(id),
  role           text not null check (role in ('driver', 'passenger')),
  origin_lat     double precision not null,
  origin_lng     double precision not null,
  dest_name      text not null,
  dest_place_id  text,
  dest_lat       double precision not null,
  dest_lng       double precision not null,
  window_start   timestamptz not null,               -- acceptable departure window
  window_end     timestamptz not null,
  party_size     int not null default 1 check (party_size > 0),
  max_detour_mi  double precision not null default 2.0,
  needs_vehicle  boolean not null default false,     -- driver without their own car
  status         text not null default 'open'
                 check (status in ('open', 'matched', 'confirmed', 'cancelled')),
  created_at     timestamptz not null default now(),
  check (window_end > window_start)
);

create table if not exists matches (
  id                    serial primary key,
  driver_trip_id        int not null references trips(id),
  vehicle_id            int references vehicles(id),  -- null when driver brings own car
  depart_time           timestamptz not null,
  pickup_order          jsonb not null default '[]',  -- [trip_id, ...]
  route                 jsonb,                        -- {polyline, stops:[{trip_id,kind,lat,lng}], legs:[{distance_mi,duration_min}], distance_mi, duration_min, source}
  status                text not null default 'proposed'
                        check (status in ('proposed', 'confirmed', 'at_risk', 'cancelled')),
  raw_cost_cents        int,                          -- rental + energy, before the per-person round-up
  total_cost_cents      int,                          -- cost_per_person_cents * group size (what riders pay)
  cost_per_person_cents int,
  pricing               jsonb,                        -- {rental_hours, rental_cents, energy_cents, group_size, ...}
  impact                jsonb,
  reasons               jsonb,                        -- {grouping:[str], vehicle:[str], vehicle_options:[...]}
  explanation           text,
  assumptions           jsonb,
  last_change           jsonb,                        -- {cause, before, after} from the latest replan
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create table if not exists match_members (
  match_id     int not null references matches(id),
  trip_id      int not null references trips(id),
  status       text not null default 'pending' check (status in ('pending', 'accepted', 'cancelled')),
  match_score  double precision,
  primary key (match_id, trip_id)
);

create table if not exists bookings (
  id          serial primary key,
  match_id    int not null references matches(id),
  vehicle_id  int not null references vehicles(id),
  start_ts    timestamptz not null,
  end_ts      timestamptz not null,
  hours       numeric(4,1) not null,
  price_cents int not null,
  status      text not null default 'requested'
              check (status in ('requested', 'approved', 'declined', 'cancelled')),
  created_at  timestamptz not null default now()
);

create table if not exists route_cache (
  key          text primary key,                    -- rounded coords + travel mode (+ waypoints for routes)
  distance_mi  double precision not null,
  duration_min double precision not null,
  polyline     text,
  payload      jsonb,                               -- extra data, e.g. optimized waypoint order
  fetched_at   timestamptz not null default now()
);

create table if not exists agent_runs (
  id                bigserial primary key,
  ts                timestamptz not null default now(),
  trigger           text not null,
  planner           text not null check (planner in ('gemini', 'deterministic')),
  tool_calls        jsonb not null default '[]',
  raw_output        jsonb,
  validator_errors  jsonb not null default '[]',
  retries           int not null default 0,
  latency_ms        int,
  fallback_used     boolean not null default false
);

create table if not exists events (
  id       bigserial primary key,
  ts       timestamptz not null default now(),
  kind     text not null,
  payload  jsonb not null default '{}'
);

create index if not exists trips_status_idx on trips (status);
create index if not exists bookings_vehicle_idx on bookings (vehicle_id) where status in ('requested', 'approved');
