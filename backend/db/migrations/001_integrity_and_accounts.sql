-- Constraints also protect writes outside our API. Singleton integer ranges use
-- PostgreSQL's built-in GiST operators, with no extension needed locally or on Neon.

-- Display names are not account identifiers. Multiple students can be Alex.
alter table users drop constraint if exists users_name_key;
alter table users add column created_at timestamptz not null default now();
alter table users add constraint users_valid_profile check (
  length(trim(name)) between 1 and 120
  and home_lat between -90 and 90 and home_lng between -180 and 180
  and roles <@ array['driver', 'passenger', 'owner']::text[]
  and array_position(roles, null) is null
  and (rating is null or rating between 0 and 5)
);

-- Subject is the verified external account ID, never a display name. Linking
-- identities is a trusted adapter operation, not proof of authentication.
create table user_identities (
  provider text not null check (length(trim(provider)) between 1 and 80),
  subject text not null check (length(trim(subject)) between 1 and 255),
  user_id int not null references users(id),
  created_at timestamptz not null default now(),
  primary key (provider, subject)
);
create index user_identities_user_idx on user_identities(user_id);

alter table vehicles add column efficiency_source text not null default 'Owner-supplied estimate; not independently verified';
alter table vehicles add constraint vehicles_valid_specs check (
  avail_end > avail_start and isfinite(avail_start) and isfinite(avail_end)
  and efficiency > 0 and efficiency < 'Infinity'::float8
  and range_mi > 0 and range_mi < 'Infinity'::float8
  and lat between -90 and 90 and lng between -180 and 180
  and length(trim(make_model)) > 0
);
alter table trips add constraint trips_valid_location check (
  origin_lat between -90 and 90 and origin_lng between -180 and 180
  and dest_lat between -90 and 90 and dest_lng between -180 and 180
  and max_detour_mi >= 0 and max_detour_mi < 'Infinity'::float8
  and isfinite(window_start) and isfinite(window_end)
  and length(trim(dest_name)) > 0
);
alter table bookings add constraint bookings_valid_period check (
  end_ts > start_ts and isfinite(start_ts) and isfinite(end_ts)
  and hours > 0 and price_cents >= 0
);
alter table bookings add constraint bookings_no_vehicle_overlap exclude using gist (
  int8range(vehicle_id::bigint, vehicle_id::bigint, '[]') with &&,
  tstzrange(start_ts, end_ts, '[)') with &&
) where (status in ('requested', 'approved')) deferrable initially deferred;
create unique index bookings_one_live_per_match on bookings(match_id)
  where status in ('requested', 'approved');

-- Deferred so a replan can move a rider between matches in one transaction.
alter table match_members add constraint members_one_live_match exclude using gist (
  int8range(trip_id::bigint, trip_id::bigint, '[]') with &&
) where (status <> 'cancelled') deferrable initially deferred;

alter table matches add constraint matches_valid_costs check (
  raw_cost_cents >= 0 and total_cost_cents >= raw_cost_cents and cost_per_person_cents >= 0
);
create index trips_user_idx on trips(user_id, created_at desc);
create index vehicles_owner_idx on vehicles(owner_id);
create index members_trip_idx on match_members(trip_id);
create index bookings_match_idx on bookings(match_id, id desc);
create index matches_driver_idx on matches(driver_trip_id);
