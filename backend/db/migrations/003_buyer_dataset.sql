-- Simulated driving dataset for the buyer portal (formerly hardcoded in the frontend's buyerData.ts).
create table buyer_trips (
  id text primary key,
  driver_id text not null,
  started_at timestamptz not null,
  miles double precision not null check (miles >= 0),
  duration_minutes integer not null check (duration_minutes >= 0),
  estimated_energy_kwh double precision not null check (estimated_energy_kwh >= 0)
);

create table buyer_events (
  id text primary key,
  trip_id text not null references buyer_trips(id) on delete cascade,
  driver_id text not null,
  type text not null check (type in ('hard_brake', 'rapid_acceleration', 'sharp_turn')),
  at timestamptz not null,
  offset_seconds integer not null,
  severity text not null check (severity in ('Review', 'Watch')),
  detail text not null,
  value double precision not null,
  unit text not null,
  threshold double precision not null
);
create index buyer_events_trip_idx on buyer_events(trip_id);
