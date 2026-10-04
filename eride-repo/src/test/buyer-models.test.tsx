import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BuyerModels, extraDisclaimer, toCsv } from "@/components/BuyerModels";
import { BuyerPortal } from "@/routes/buyer";
import * as sample from "@/lib/buyerData";
import type { BuyerInsights, TripScore } from "@/lib/account-api";

afterEach(cleanup);

function score(over: Partial<TripScore> = {}): TripScore {
  return {
    tripId: "TR-001",
    driverId: "D1",
    startedAt: "2026-09-21T16:00:00.000Z",
    miles: 10,
    features: {
      duration_minutes: 27,
      avg_speed_mph: 22.2,
      kwh_per_100mi: 24,
      hard_brakes_per_100mi: 10,
      rapid_accels_per_100mi: 0,
      sharp_turns_per_100mi: 0,
      hour_of_day: 16,
    },
    anomalyScore: -0.52,
    anomalyFlagged: false,
    riskProbability: 0.1,
    predictedKwhPerMi: 0.24,
    actualKwhPerMi: 0.25,
    scoredBy: "fixture",
    ...over,
  };
}

const INSIGHTS: BuyerInsights = {
  simulated: true,
  validated: false,
  liveBookingTrips: 0,
  voidedBookingTrips: 0,
  disclaimer: "Models trained on simulated data. Not a validated safety score.",
  runs: [
    {
      name: "anomaly_isolation_forest",
      kind: "anomaly_detection",
      trained_at: "2026-10-04T00:00:00Z",
      library: "scikit-learn 1.9.1",
      dataset_rows: 48,
      random_seed: 20261004,
      features: ["miles", "kwh_per_100mi"],
      metrics: { flagged: 2, trips: 48 },
      notes: "Unsupervised. A flag means unusual for this simulated fleet, not unsafe.",
    },
    {
      name: "risk_gradient_boosting",
      kind: "driver_risk",
      trained_at: "2026-10-04T00:00:00Z",
      library: "scikit-learn 1.9.1",
      dataset_rows: 48,
      random_seed: 20261004,
      features: ["miles", "hour_of_day"],
      metrics: {
        cv_roc_auc: 0.7285,
        cv_accuracy: 0.6875,
        trips: 48,
        positives: 16,
        logistic_baseline_cv_roc_auc: 0.5566,
      },
      notes: "Gradient boosting. Not a validated safety score.",
    },
    {
      name: "energy_linear",
      kind: "energy_regression",
      trained_at: "2026-10-04T00:00:00Z",
      library: "scikit-learn 1.9.1",
      dataset_rows: 48,
      random_seed: 20261004,
      features: ["miles", "avg_speed_mph"],
      metrics: { test_mae: 0.003386, test_r2: 0.9291, test_rows: 15, train_rows: 33 },
      notes: "Ordinary least squares on simulated trips with a fixed formula behind the target.",
    },
  ],
  tripScores: [
    score({ tripId: "TR-009", driverId: "D3", anomalyFlagged: true, anomalyScore: -0.66 }),
    score({ tripId: "TR-014", driverId: "D5", anomalyFlagged: true, anomalyScore: -0.6 }),
    score({ tripId: "TR-021", driverId: "D2" }),
  ],
  driverRisk: [
    { driverId: "D5", trips: 8, riskScore: 75, meanProbability: 0.75 },
    { driverId: "D3", trips: 8, riskScore: 74, meanProbability: 0.74 },
    { driverId: "D1", trips: 8, riskScore: 0, meanProbability: 0.003 },
  ],
};

describe("Buyer models section", () => {
  it("labels the models as trained on simulated data and not validated", () => {
    render(<BuyerModels data={INSIGHTS} onSelectTrip={() => {}} />);
    expect(screen.getByRole("note")).toHaveTextContent(
      /Models trained on simulated data, not validated/,
    );
    // The caveat appears in the banner and again on the risk card, which is deliberate.
    expect(screen.getAllByText(/[Nn]ot a validated safety score/).length).toBeGreaterThanOrEqual(2);
  });

  it("lists the anomaly flagged trips with their scores and links each to the timeline", () => {
    const picked: string[] = [];
    render(<BuyerModels data={INSIGHTS} onSelectTrip={(id) => picked.push(id)} />);
    expect(screen.getByText("2")).toBeInTheDocument();
    const flagged = screen.getByRole("button", { name: /Inspect flagged trip TR-009 by D3/ });
    expect(flagged).toHaveTextContent("-0.660");
    expect(screen.queryByRole("button", { name: /TR-021/ })).not.toBeInTheDocument();
    fireEvent.click(flagged);
    expect(picked).toEqual(["TR-009"]);
  });

  it("ranks drivers with bars and never claims a validated score", () => {
    render(<BuyerModels data={INSIGHTS} onSelectTrip={() => {}} />);
    expect(screen.getByText("0.7285")).toBeInTheDocument();
    expect(screen.getByText(/A logistic baseline scored 0.5566/)).toBeInTheDocument();
    expect(screen.getByText("75")).toBeInTheDocument();
    expect(screen.getByText("D5")).toBeInTheDocument();
  });

  it("shows the energy fit with its MAE, R2 and the caveat", () => {
    render(<BuyerModels data={INSIGHTS} onSelectTrip={() => {}} />);
    expect(screen.getByText("0.003386")).toBeInTheDocument();
    expect(screen.getByText("0.9291")).toBeInTheDocument();
    expect(screen.getByText(/follow a fixed formula/)).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Predicted against actual kilowatt hours per mile/ }),
    ).toBeInTheDocument();
  });

  it("draws the perfect prediction line as y = x, bottom left to top right", () => {
    const { container } = render(<BuyerModels data={INSIGHTS} onSelectTrip={() => {}} />);
    const line = container.querySelector(".buyer-energy-ideal line");
    expect(line).not.toBeNull();
    // In SVG coordinates y grows downwards, so bottom left is (0,100) and top right is (100,0).
    expect(line!.getAttribute("x1")).toBe("0");
    expect(line!.getAttribute("y1")).toBe("100");
    expect(line!.getAttribute("x2")).toBe("100");
    expect(line!.getAttribute("y2")).toBe("0");
    const svg = container.querySelector(".buyer-energy-ideal");
    expect(svg!.getAttribute("viewBox")).toBe("0 0 100 100");
    expect(svg!.getAttribute("preserveAspectRatio")).toBe("none");
  });

  it("labels both axes and shows the same range on each", () => {
    const { container } = render(<BuyerModels data={INSIGHTS} onSelectTrip={() => {}} />);
    expect(screen.getByText("predicted kWh per mile")).toBeInTheDocument();
    expect(screen.getByText("actual kWh per mile")).toBeInTheDocument();
    // A point on the diagonal means predicted equals actual, which only reads correctly if both
    // axes cover the same range.
    const yTicks = [...container.querySelectorAll(".buyer-energy-yticks span")].map((n) => n.textContent);
    const xTicks = [...container.querySelectorAll(".buyer-energy-xaxis span")]
      .map((n) => n.textContent)
      .filter((t) => t !== "actual kWh per mile");
    expect(yTicks).toEqual([...xTicks].reverse());
    expect(screen.getByText(/The diagonal is a perfect prediction/)).toBeInTheDocument();
  });

  it("puts a point above the diagonal when the prediction was high", () => {
    const high = score({ tripId: "TR-HI", actualKwhPerMi: 0.22, predictedKwhPerMi: 0.3 });
    const { container } = render(
      <BuyerModels data={{ ...INSIGHTS, tripScores: [high] }} onSelectTrip={() => {}} />,
    );
    const dot = container.querySelector(".buyer-energy-dot") as HTMLElement;
    // left tracks actual, bottom tracks predicted, so predicting high sits above the line.
    expect(parseFloat(dot.style.bottom)).toBeGreaterThan(parseFloat(dot.style.left));
  });

  it("states the simulated data warning once, not twice", () => {
    render(<BuyerModels data={INSIGHTS} onSelectTrip={() => {}} />);
    const banner = screen.getByRole("note").textContent ?? "";
    const occurrences = banner.toLowerCase().split("models trained on simulated data").length - 1;
    expect(occurrences).toBe(1);
    expect(banner).toContain("Models trained on simulated data, not validated.");
    // The rest of the backend disclaimer is still shown, so no information is lost.
    expect(banner).toContain("Not a validated safety score.");
  });

  it("keeps the whole disclaimer when it does not repeat the banner", () => {
    expect(extraDisclaimer("Models trained on simulated data. No real telemetry was used."))
      .toBe("No real telemetry was used.");
    expect(extraDisclaimer("models trained on simulated data, Not validated outside this set."))
      .toBe("Not validated outside this set.");
    expect(extraDisclaimer("Something else entirely.")).toBe("Something else entirely.");
    expect(extraDisclaimer("")).toBe("");
  });

  it("explains how each score is computed only when asked", () => {
    render(<BuyerModels data={INSIGHTS} onSelectTrip={() => {}} />);
    expect(screen.queryByText(/not unsafe/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /How the flagging works/ }));
    expect(screen.getByText(/not unsafe/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /How this score is computed/ }));
    expect(screen.getByText(/Gradient boosting. Not a validated safety score./)).toBeInTheDocument();
    expect(screen.getByText(/Inputs: miles, hour_of_day/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /How the fit is measured/ }));
    expect(screen.getByText(/fixed formula behind the target/)).toBeInTheDocument();
  });

  it("says how many trips are unscored rather than pretending they are fine", () => {
    const withUnscored: BuyerInsights = {
      ...INSIGHTS,
      tripScores: [
        ...INSIGHTS.tripScores,
        score({ tripId: "TR-099", scoredBy: "unscored", anomalyScore: null, anomalyFlagged: null }),
      ],
    };
    render(<BuyerModels data={withUnscored} onSelectTrip={() => {}} />);
    expect(screen.getByText(/1 trips are unscored/)).toBeInTheDocument();
  });

  it("builds a CSV of features and scores with a header row", () => {
    const csv = toCsv(INSIGHTS.tripScores);
    const lines = csv.trim().split("\n");
    expect(lines).toHaveLength(4);
    expect(lines[0]).toContain("trip_id,driver_id,started_at,miles,duration_minutes");
    expect(lines[0]).toContain("anomaly_score,anomaly_flagged,risk_probability");
    expect(lines[1]).toContain("TR-009,D3");
    expect(lines[1]).toContain("-0.66");
  });

  it("leaves a missing score blank in the CSV instead of writing null", () => {
    const csv = toCsv([score({ anomalyScore: null, anomalyFlagged: null, scoredBy: "unscored" })]);
    expect(csv).not.toContain("null");
    expect(csv.trim().split("\n")[1]).toContain(",,");
  });

  it("offers the CSV download and triggers it", () => {
    const click = vi.fn();
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => {
      if (tag === "a") return { click, set href(_v: string) {}, set download(_v: string) {} };
      return document.createElementNS("http://www.w3.org/1999/xhtml", tag);
    }) as typeof document.createElement);
    render(<BuyerModels data={INSIGHTS} onSelectTrip={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Download features and scores/ }));
    expect(create).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});

describe("Buyer portal with models", () => {
  it("keeps the simulated data badge and the JSON download alongside the new section", () => {
    render(<BuyerPortal data={sample} insights={INSIGHTS} />);
    expect(screen.getByText("Simulated data")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download sample/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "What the models say" })).toBeInTheDocument();
    expect(screen.getByText("04 / Models")).toBeInTheDocument();
  });

  it("renders the rest of the portal when the insights request has not arrived", () => {
    render(<BuyerPortal data={sample} />);
    expect(screen.getByText("Simulated data")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "What the models say" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Flagged events" })).toBeInTheDocument();
  });

  it("selecting a flagged trip moves the existing trip detail panel to it", () => {
    const trip = sample.demoTrips.find((t) => t.events.length > 0)!;
    const flagged = [score({ tripId: trip.id, driverId: trip.driverId, anomalyFlagged: true })];
    render(<BuyerPortal data={sample} insights={{ ...INSIGHTS, tripScores: flagged }} />);
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(`Inspect flagged trip ${trip.id}`) }),
    );
    const detail = screen.getByRole("region", { name: "Trip details" });
    expect(within(detail).getByText("Why it was flagged")).toBeInTheDocument();
    expect(within(detail).getByText(trip.id)).toBeInTheDocument();
  });
});
