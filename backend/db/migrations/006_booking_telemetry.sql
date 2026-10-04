-- Confirmed rides produce one simulated telemetry trip each, so the data portal has something that
-- came from a real booking. The telemetry itself is generated, never measured.

alter table buyer_trips add column source text not null default 'fixture'
  check (source in ('fixture', 'booking'));
alter table buyer_trips add column simulated boolean not null default true;
alter table buyer_trips add column match_id integer references matches(id) on delete set null;
alter table buyer_trips add column vehicle_id integer references vehicles(id) on delete set null;
-- A cancelled ride keeps its row and is marked instead, so the history stays honest.
alter table buyer_trips add column voided boolean not null default false;

-- One generated trip per match, whatever happens on replans or repeated accepts.
create unique index buyer_trips_one_per_match on buyer_trips (match_id)
  where match_id is not null;
create index buyer_trips_source_idx on buyer_trips (source) where source = 'booking';

-- A clearly labelled demo payout to the car's owner for each confirmed ride. Not real money.
create table owner_data_earnings (
  match_id      integer primary key references matches(id) on delete cascade,
  owner_id      integer not null references users(id),
  vehicle_id    integer references vehicles(id) on delete set null,
  buyer_trip_id text references buyer_trips(id) on delete set null,
  amount_cents  integer not null check (amount_cents >= 0),
  simulated     boolean not null default true,
  created_at    timestamptz not null default now()
);
create index owner_data_earnings_owner_idx on owner_data_earnings (owner_id);
