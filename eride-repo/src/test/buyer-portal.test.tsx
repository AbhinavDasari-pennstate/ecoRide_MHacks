import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { BuyerPortal } from "@/routes/buyer";
import * as sample from "@/lib/buyerData";

afterEach(cleanup);

describe("Buyer portal", () => {
  it("filters events by driver and lets a buyer inspect the reason for a flag", () => {
    render(<BuyerPortal data={sample} />);
    expect(screen.getByText("Simulated data")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Compare driver D4" }));
    const feed = screen.getByRole("region", { name: "Flagged events" });
    const events = within(feed).getAllByRole("button", { name: /^Inspect / });
    expect(events.length).toBeGreaterThan(0);
    for (const event of events) expect(event.getAttribute("aria-label")).toContain("D4");

    fireEvent.click(events[0]!);
    const detail = screen.getByRole("region", { name: "Trip details" });
    expect(within(detail).getByText("D4")).toBeInTheDocument();
    expect(within(detail).getByText("Why it was flagged")).toBeInTheDocument();
    expect(within(detail).getByText(/demo threshold/i, { selector: "p" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show all drivers" }));
    expect(within(feed).getAllByRole("button", { name: /^Inspect / }).length).toBeGreaterThan(
      events.length,
    );
  });

  it("switches the comparison metric without losing the chosen driver", () => {
    render(<BuyerPortal data={sample} />);
    fireEvent.click(screen.getByRole("button", { name: "Compare driver D2" }));
    fireEvent.click(screen.getByRole("button", { name: "Estimated energy" }));
    expect(screen.getByText("kWh per 100 miles · lower is less energy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare driver D2" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Hard braking" }));
    expect(
      screen.getByText("Hard brakes per 100 miles · lower is fewer events"),
    ).toBeInTheDocument();
  });

  it("clears stale trip details when a driver has no events and restores them after clearing filters", () => {
    render(<BuyerPortal data={sample} />);
    fireEvent.click(screen.getByRole("button", { name: "Compare driver D1" }));
    const feed = screen.getByRole("region", { name: "Flagged events" });
    expect(within(feed).queryAllByRole("button", { name: /^Inspect / })).toHaveLength(0);
    expect(within(feed).getByText("No matching events")).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Trip details" })).queryByText(
        "Why it was flagged",
      ),
    ).not.toBeInTheDocument();
    fireEvent.click(within(feed).getByRole("button", { name: "Clear filters" }));
    expect(within(feed).getAllByRole("button", { name: /^Inspect / }).length).toBeGreaterThan(0);
    expect(
      within(screen.getByRole("region", { name: "Trip details" })).getByText("Why it was flagged"),
    ).toBeInTheDocument();
  });
});
