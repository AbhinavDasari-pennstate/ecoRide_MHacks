import { useState } from "react";
import { ArrowDownToLine, Brain, CircleAlert, Gauge, Info, TrendingUp } from "lucide-react";
import type { BuyerInsights, ModelRun, TripScore } from "@/lib/account-api";

const date = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "America/Detroit",
});
const time = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "America/Detroit",
});

const CSV_COLUMNS = [
  "trip_id",
  "driver_id",
  "started_at",
  "miles",
  "duration_minutes",
  "avg_speed_mph",
  "kwh_per_100mi",
  "hard_brakes_per_100mi",
  "rapid_accels_per_100mi",
  "sharp_turns_per_100mi",
  "hour_of_day",
  "anomaly_score",
  "anomaly_flagged",
  "risk_probability",
  "predicted_kwh_per_mi",
  "actual_kwh_per_mi",
  "scored_by",
] as const;

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Per-trip features and scores as CSV. Same numbers the charts above are drawn from. */
export function toCsv(scores: TripScore[]): string {
  const rows = scores.map((s) =>
    [
      s.tripId,
      s.driverId,
      s.startedAt,
      s.miles,
      s.features["duration_minutes"],
      s.features["avg_speed_mph"],
      s.features["kwh_per_100mi"],
      s.features["hard_brakes_per_100mi"],
      s.features["rapid_accels_per_100mi"],
      s.features["sharp_turns_per_100mi"],
      s.features["hour_of_day"],
      s.anomalyScore,
      s.anomalyFlagged,
      s.riskProbability,
      s.predictedKwhPerMi,
      s.actualKwhPerMi,
      s.scoredBy,
    ]
      .map(cell)
      .join(","),
  );
  return [CSV_COLUMNS.join(","), ...rows].join("\n") + "\n";
}

function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function metric(run: ModelRun | undefined, key: string): string {
  const value = run?.metrics?.[key];
  return value === undefined || value === null ? "n/a" : String(value);
}

export function BuyerModels({
  data,
  onSelectTrip,
}: {
  data: BuyerInsights;
  onSelectTrip: (tripId: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const runs = Object.fromEntries(data.runs.map((r) => [r.name, r])) as Record<string, ModelRun>;
  const anomaly = runs["anomaly_isolation_forest"];
  const risk = runs["risk_gradient_boosting"];
  const energy = runs["energy_linear"];

  const flagged = data.tripScores
    .filter((s) => s.anomalyFlagged)
    .sort((a, b) => (a.anomalyScore ?? 0) - (b.anomalyScore ?? 0));
  const unscored = data.tripScores.filter((s) => s.scoredBy === "unscored").length;
  const energyPoints = data.tripScores.filter(
    (s) => s.predictedKwhPerMi !== null && s.actualKwhPerMi !== null,
  );
  const maxRisk = Math.max(1, ...data.driverRisk.map((d) => d.riskScore));
  const values = energyPoints.flatMap((s) => [s.predictedKwhPerMi!, s.actualKwhPerMi!]);
  const lo = Math.min(...values, 0.2);
  const hi = Math.max(...values, 0.3);
  const pos = (v: number) => ((v - lo) / (hi - lo || 1)) * 100;

  return (
    <section className="buyer-panel buyer-models" aria-labelledby="models-title">
      <div className="buyer-panel-heading">
        <div>
          <p className="buyer-eyebrow">04 / Models</p>
          <h2 id="models-title">What the models say</h2>
          <p>Three models fitted offline on this dataset. Open each note to see how it works.</p>
        </div>
        <Brain size={19} aria-hidden="true" />
      </div>

      <p className="buyer-model-banner" role="note">
        <CircleAlert size={15} aria-hidden="true" />
        Models trained on simulated data, not validated. {data.disclaimer}
      </p>

      <p className="buyer-live-link">
        Trips from live bookings: <strong>{data.liveBookingTrips}</strong>
        {data.voidedBookingTrips > 0 ? ` (${data.voidedBookingTrips} voided after cancellation)` : ""}.
        Each confirmed ride adds one trip whose distance comes from the planned route. The driving
        events and energy are generated from the booking, not recorded by a device.
      </p>

      <div className="buyer-model-actions">
        <button
          className="buyer-download"
          onClick={() => download("eride-trip-features-scores.csv", toCsv(data.tripScores), "text/csv")}
        >
          <ArrowDownToLine size={16} /> Download features and scores <span>CSV</span>
        </button>
      </div>

      <div className="buyer-model-grid">
        <article className="buyer-model-card" aria-labelledby="model-anomaly">
          <header>
            <Gauge size={17} aria-hidden="true" />
            <h3 id="model-anomaly">Unusual trips</h3>
          </header>
          <p className="buyer-model-stat">
            <strong>{flagged.length}</strong> of {data.tripScores.length} flagged
          </p>
          <p className="buyer-model-sub">
            IsolationForest, unsupervised, so there is no accuracy to report.
            {unscored > 0 ? ` ${unscored} trips are unscored.` : ""}
          </p>
          <ul className="buyer-model-list">
            {flagged.slice(0, 8).map((s) => (
              <li key={s.tripId}>
                <button
                  onClick={() => onSelectTrip(s.tripId)}
                  aria-label={`Inspect flagged trip ${s.tripId} by ${s.driverId}`}
                >
                  <span className="buyer-model-trip">
                    {s.tripId}
                    {s.source === "booking" && <span className="buyer-live-tag">live booking</span>}
                  </span>
                  <span className="buyer-model-meta">
                    {s.driverId} · {date.format(new Date(s.startedAt))}{" "}
                    {time.format(new Date(s.startedAt))}
                  </span>
                  <span className="buyer-model-score">{(s.anomalyScore ?? 0).toFixed(3)}</span>
                </button>
              </li>
            ))}
            {flagged.length === 0 && <li className="buyer-model-sub">Nothing flagged.</li>}
          </ul>
          <button className="buyer-model-how" onClick={() => setOpen(open === "a" ? null : "a")}>
            <Info size={13} /> How the flagging works
          </button>
          {open === "a" && <p className="buyer-model-note">{anomaly?.notes}</p>}
        </article>

        <article className="buyer-model-card" aria-labelledby="model-risk">
          <header>
            <TrendingUp size={17} aria-hidden="true" />
            <h3 id="model-risk">Driver risk ranking</h3>
          </header>
          <p className="buyer-model-stat">
            <strong>{metric(risk, "cv_roc_auc")}</strong> cross-validated ROC AUC
          </p>
          <p className="buyer-model-sub">
            Gradient boosting over {metric(risk, "trips")} trips with {metric(risk, "positives")}{" "}
            positives. A logistic baseline scored {metric(risk, "logistic_baseline_cv_roc_auc")}.
            Not a validated safety score.
          </p>
          <ul className="buyer-risk-bars">
            {data.driverRisk.map((d) => (
              <li key={d.driverId}>
                <span className="buyer-risk-driver">{d.driverId}</span>
                <span className="buyer-risk-track">
                  <span
                    className="buyer-risk-fill"
                    style={{ width: `${(d.riskScore / maxRisk) * 100}%` }}
                  />
                </span>
                <strong>{d.riskScore}</strong>
                <span className="buyer-model-meta">{d.trips} trips</span>
              </li>
            ))}
          </ul>
          <button className="buyer-model-how" onClick={() => setOpen(open === "r" ? null : "r")}>
            <Info size={13} /> How this score is computed
          </button>
          {open === "r" && (
            <div className="buyer-model-note">
              <p>{risk?.notes}</p>
              <p className="buyer-model-features">
                Inputs: {risk?.features.join(", ")}. Score is the mean predicted chance across a
                driver's trips, times 100.
              </p>
            </div>
          )}
        </article>

        <article className="buyer-model-card buyer-model-wide" aria-labelledby="model-energy">
          <header>
            <Gauge size={17} aria-hidden="true" />
            <h3 id="model-energy">Energy use per mile, predicted against actual</h3>
          </header>
          <p className="buyer-model-stat">
            MAE <strong>{metric(energy, "test_mae")}</strong> kWh per mile, R2{" "}
            <strong>{metric(energy, "test_r2")}</strong>
          </p>
          <p className="buyer-model-sub">
            Held out {metric(energy, "test_rows")} of {data.tripScores.length} trips. The energy
            figures in this dataset follow a fixed formula, so a strong fit shows the regression
            recovered that formula, not that it would predict a real car.
          </p>
          <div
            className="buyer-energy-chart"
            role="img"
            aria-label={`Predicted against actual kilowatt hours per mile for ${energyPoints.length} simulated trips`}
          >
            <span className="buyer-energy-ideal" />
            {energyPoints.map((s) => (
              <span
                key={s.tripId}
                className="buyer-energy-dot"
                style={{
                  left: `${pos(s.actualKwhPerMi!)}%`,
                  bottom: `${pos(s.predictedKwhPerMi!)}%`,
                }}
                title={`${s.tripId}: actual ${s.actualKwhPerMi!.toFixed(3)}, predicted ${s.predictedKwhPerMi!.toFixed(3)}`}
              />
            ))}
          </div>
          <div className="buyer-energy-axes">
            <span>actual kWh per mile, {lo.toFixed(2)} to {hi.toFixed(2)}</span>
            <span>the line is a perfect prediction</span>
          </div>
          <button className="buyer-model-how" onClick={() => setOpen(open === "e" ? null : "e")}>
            <Info size={13} /> How the fit is measured
          </button>
          {open === "e" && (
            <div className="buyer-model-note">
              <p>{energy?.notes}</p>
              <p className="buyer-model-features">Inputs: {energy?.features.join(", ")}.</p>
            </div>
          )}
        </article>
      </div>

      <p className="buyer-model-footnote">
        Fitted with {anomaly?.library ?? "scikit-learn"} at seed {anomaly?.random_seed ?? "n/a"}, so
        a rerun reproduces these numbers. Regenerate with scripts/train_buyer_models.py.
      </p>
    </section>
  );
}
