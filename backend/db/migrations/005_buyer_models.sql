-- Model outputs for the simulated buyer dataset. Written by scripts/train_buyer_models.py and
-- restored from fixtures/buyer_models.json, so the API never needs scikit-learn at runtime.

create table buyer_model_runs (
  name          text primary key,              -- anomaly_isolation_forest | risk_logistic | energy_linear
  kind          text not null,
  trained_at    timestamptz not null,
  library       text not null,                 -- the exact library and version that fitted it
  dataset_rows  integer not null check (dataset_rows >= 0),
  random_seed   integer not null,
  features      jsonb not null default '[]',   -- ordered feature names the model consumes
  metrics       jsonb not null default '{}',   -- reported honestly, including the held-out split
  params        jsonb not null default '{}',   -- coefficients, so runtime scoring stays pure Python
  notes         text not null default ''       -- plain language: how it works and what it cannot claim
);

create table buyer_trip_scores (
  trip_id              text primary key references buyer_trips(id) on delete cascade,
  features             jsonb not null default '{}',
  anomaly_score        double precision,       -- null means not scored
  anomaly_flagged      boolean,
  risk_probability     double precision check (risk_probability between 0 and 1),
  predicted_kwh_per_mi double precision check (predicted_kwh_per_mi >= 0),
  actual_kwh_per_mi    double precision check (actual_kwh_per_mi >= 0),
  scored_by            text not null default 'fixture'
                       check (scored_by in ('fixture', 'runtime', 'unscored')),
  scored_at            timestamptz not null default now()
);

create table buyer_driver_risk (
  driver_id       text primary key,
  trips           integer not null check (trips >= 0),
  risk_score      integer not null check (risk_score between 0 and 100),
  mean_probability double precision not null check (mean_probability between 0 and 1),
  computed_at     timestamptz not null default now()
);

create index buyer_trip_scores_flagged_idx on buyer_trip_scores (anomaly_flagged)
  where anomaly_flagged;
