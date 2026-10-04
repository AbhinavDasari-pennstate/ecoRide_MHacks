-- Latest shared position per traveler in a match. Overwritten in place; no location history is kept.
create table live_locations (
  match_id integer not null references matches(id) on delete cascade,
  user_id integer not null references users(id) on delete cascade,
  lat double precision not null check (lat between -90 and 90),
  lng double precision not null check (lng between -180 and 180),
  accuracy_m double precision check (accuracy_m >= 0),
  updated_at timestamptz not null default now(),
  primary key (match_id, user_id)
);
