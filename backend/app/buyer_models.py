"""Feature building and pure-Python scoring for the buyer dataset models.

The models are fitted offline by scripts/train_buyer_models.py with scikit-learn. Their fitted
parameters are committed to fixtures/buyer_models.json, and everything in this module scores from
those numbers with plain arithmetic, so the API needs neither scikit-learn nor numpy.

The exception is the isolation forest, whose scoring cannot be reduced to a few coefficients. It is
loaded from a joblib file when one is present and scikit-learn is importable; otherwise a trip is
recorded as unscored rather than guessed at.

Everything here runs on simulated data. Nothing in it is validated against real driving.
"""
import math
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
FOREST_FILE = MODEL_DIR / "anomaly_isolation_forest.joblib"

ANOMALY = "anomaly_isolation_forest"
RISK = "risk_gradient_boosting"
ENERGY = "energy_linear"

# Ordered feature sets. The risk model deliberately excludes every event count and severity, so a
# driver's score cannot be read straight off the labels it is trained against.
ANOMALY_FEATURES = ["miles", "duration_minutes", "avg_speed_mph", "kwh_per_100mi",
                    "hard_brakes_per_100mi", "rapid_accels_per_100mi", "sharp_turns_per_100mi"]
RISK_FEATURES = ["miles", "duration_minutes", "avg_speed_mph", "kwh_per_100mi", "hour_of_day"]
ENERGY_FEATURES = ["miles", "duration_minutes", "avg_speed_mph", "hard_brakes_per_100mi",
                   "rapid_accels_per_100mi", "sharp_turns_per_100mi", "hour_of_day"]

TYPE_COLUMN = {"hard_brake": "hard_brakes", "rapid_acceleration": "rapid_accels",
               "sharp_turn": "sharp_turns"}


def features_for(trip: dict, events: list[dict]) -> dict:
    """One feature row from a trip and its events, in the shape both training and runtime use.

    trip needs miles, durationMinutes, estimatedEnergyKwh and startedAt (ISO, UTC).
    events need type and severity.
    """
    miles = float(trip["miles"]) or 0.0
    minutes = float(trip["durationMinutes"]) or 0.0
    kwh = float(trip["estimatedEnergyKwh"])
    per_100 = lambda n: round(n / miles * 100, 4) if miles else 0.0
    counts = {name: 0 for name in TYPE_COLUMN.values()}
    for event in events:
        column = TYPE_COLUMN.get(event["type"])
        if column:
            counts[column] += 1
    return {
        "miles": round(miles, 4),
        "duration_minutes": round(minutes, 4),
        "avg_speed_mph": round(miles / minutes * 60, 4) if minutes else 0.0,
        "kwh_per_100mi": per_100(kwh),
        "hard_brakes_per_100mi": per_100(counts["hard_brakes"]),
        "rapid_accels_per_100mi": per_100(counts["rapid_accels"]),
        "sharp_turns_per_100mi": per_100(counts["sharp_turns"]),
        "hour_of_day": int(str(trip["startedAt"])[11:13]) if len(str(trip["startedAt"])) >= 13 else 0,
        "hard_brakes": counts["hard_brakes"],
        "rapid_accels": counts["rapid_accels"],
        "sharp_turns": counts["sharp_turns"],
        "has_review_event": any(e.get("severity") == "Review" for e in events),
        "kwh_per_mi": round(kwh / miles, 6) if miles else 0.0,
    }


def _row(features: dict, names: list[str]) -> list[float]:
    return [float(features.get(name, 0.0)) for name in names]


def _standardise(values: list[float], mean: list[float], scale: list[float]) -> list[float]:
    return [(v - m) / (s if s else 1.0) for v, m, s in zip(values, mean, scale)]


def _leaf_value(tree: dict, row: list[float]) -> float:
    """Walk one exported regression tree. sklearn sends a sample left when value <= threshold."""
    node = 0
    while tree["left"][node] != -1:
        node = (tree["left"][node] if row[tree["feature"][node]] <= tree["threshold"][node]
                else tree["right"][node])
    return tree["value"][node]


def risk_probability(features: dict, params: dict) -> float | None:
    """P(this trip contains a Review severity event).

    Supports the gradient boosting model actually in use, whose trees are exported to JSON so no
    scikit-learn is needed here, and a standardised logistic model for comparison.
    """
    try:
        row = _row(features, params["features"])
        if params["kind"] == "gradient_boosting":
            raw = params["init_raw"] + params["learning_rate"] * sum(
                _leaf_value(tree, row) for tree in params["trees"])
        else:
            standardised = _standardise(row, params["mean"], params["scale"])
            raw = params["intercept"] + sum(c * x for c, x in zip(params["coefficients"], standardised))
        return 1.0 / (1.0 + math.exp(-raw))
    except Exception:
        return None


def predicted_kwh_per_mi(features: dict, params: dict) -> float | None:
    """Ordinary least squares on raw features."""
    try:
        value = params["intercept"] + sum(c * x for c, x in
                                          zip(params["coefficients"], _row(features, params["features"])))
        return max(0.0, value)
    except Exception:
        return None


def risk_score_from_probability(probability: float) -> int:
    """A 0 to 100 presentation of the mean probability. Not a validated risk rating."""
    return int(round(max(0.0, min(1.0, probability)) * 100))


_forest: dict | None = None
_forest_tried = False


def _load_forest() -> dict | None:
    """Load once per process. A missing file or library is expected, not an error."""
    global _forest, _forest_tried
    if not _forest_tried:
        _forest_tried = True
        try:
            import joblib                  # noqa: PLC0415  (optional at runtime by design)
            if FOREST_FILE.exists():
                _forest = joblib.load(FOREST_FILE)
        except Exception:
            _forest = None
    return _forest


def anomaly_score(features: dict) -> tuple[float | None, bool | None]:
    """(score, flagged) from the saved isolation forest, or (None, None) when it cannot be loaded.

    A missing file or a missing scikit-learn is not an error: the trip is simply recorded as
    unscored, so the API keeps working on a machine that never trained anything.
    """
    try:
        bundle = _load_forest()
        if not bundle:
            return None, None
        values = [_row(features, bundle["features"])]
        score = float(bundle["model"].score_samples(values)[0])
        return round(score, 6), bool(bundle["model"].predict(values)[0] == -1)
    except Exception:
        return None, None


def reset_forest_cache() -> None:
    """Tests and a retrain need the next call to look at the file again."""
    global _forest, _forest_tried
    _forest, _forest_tried = None, False
