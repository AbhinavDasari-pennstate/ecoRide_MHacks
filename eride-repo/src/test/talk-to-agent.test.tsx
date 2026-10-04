import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TalkToAgent, agentVariables, formatPhone } from "@/components/TalkToAgent";
import type { SessionUser } from "@/lib/account-api";

// Every variable the agent's first message and prompt use, from PLACEHOLDERS in voice.py.
const REQUIRED = ["greeting", "call_reason", "user_id", "user_name", "ride_summary"] as const;

const mocks = vi.hoisted(() => ({
  agent: undefined as { agent_id: string; phone: string } | undefined,
  user: null as { id: number; name: string; email: string; role: string } | null,
  pending: false,
}));
vi.mock("@/lib/account-api", () => ({
  useVoiceAgent: () => ({ data: mocks.agent }),
  useSession: () => ({ data: mocks.pending ? undefined : { user: mocks.user }, isPending: mocks.pending }),
}));
beforeEach(() => {
  mocks.user = null;
  mocks.pending = false;
});
afterEach(() => {
  cleanup();
  document.querySelector("script[src*='convai-widget-embed']")?.remove();
});

function mountedVariables(): Record<string, string> {
  const raw = document.querySelector("elevenlabs-convai")?.getAttribute("dynamic-variables");
  expect(raw, "the widget must carry a dynamic-variables attribute").toBeTruthy();
  return JSON.parse(raw!);
}

describe("Talk to Eco", () => {
  it("renders nothing until the backend reports an agent or a number", () => {
    mocks.agent = { agent_id: "", phone: "" };
    const { container } = render(<TalkToAgent />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a US number in a readable form and dials the raw one", () => {
    expect(formatPhone("+16282779064")).toBe("+1 628-277-9064");
    expect(formatPhone("+447700900123")).toBe("+447700900123");
    expect(formatPhone("")).toBe("");
    mocks.agent = { agent_id: "agent_123", phone: "+16282779064" };
    render(<TalkToAgent />);
    expect(screen.getByRole("link", { name: /call \+1 628-277-9064/ })).toHaveAttribute(
      "href",
      "tel:+16282779064",
    );
  });

  it("mounts the ElevenLabs widget on click and offers the phone number", () => {
    mocks.agent = { agent_id: "agent_123", phone: "+17345550199" };
    render(<TalkToAgent />);
    expect(screen.getByRole("link", { name: /call \+1 734-555-0199/ })).toHaveAttribute(
      "href",
      "tel:+17345550199",
    );
    expect(document.querySelector("elevenlabs-convai")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Talk to Eco" }));
    expect(document.querySelector("elevenlabs-convai")?.getAttribute("agent-id")).toBe("agent_123");
    expect(document.querySelector("script[src*='convai-widget-embed']")).not.toBeNull();
    expect(screen.getByRole("button")).toBeDisabled();
  });
});

describe("Talk to Eco dynamic variables", () => {
  it("supplies every variable for a signed-out visitor", () => {
    mocks.agent = { agent_id: "agent_123", phone: "" };
    render(<TalkToAgent />);
    fireEvent.click(screen.getByRole("button", { name: "Talk to Eco" }));
    const variables = mountedVariables();
    expect(Object.keys(variables).sort()).toEqual([...REQUIRED].sort());
    for (const name of REQUIRED) expect(variables[name]).toBeTypeOf("string");
    expect(variables["greeting"]).toBe(
      "Hi, this is Eco from eCARide. Do you want to book a ride, or check on one?",
    );
    expect(variables["user_id"]).toBe("");
    expect(variables["user_name"]).toBe("");
    expect(variables["call_reason"]).toBe("inbound");
    expect(variables["ride_summary"]).toBe("");
  });

  it("supplies every variable for a signed-in user, with their real name and id", () => {
    mocks.agent = { agent_id: "agent_123", phone: "" };
    mocks.user = { id: 1, name: "Alex", email: "alex@eride.demo", role: "rider" };
    render(<TalkToAgent />);
    fireEvent.click(screen.getByRole("button", { name: "Talk to Eco" }));
    const variables = mountedVariables();
    expect(Object.keys(variables).sort()).toEqual([...REQUIRED].sort());
    for (const name of REQUIRED) expect(variables[name]).toBeTypeOf("string");
    expect(variables["greeting"]).toBe(
      "Hi Alex, this is Eco from eCARide. Do you want to book a ride, or check on one?",
    );
    expect(variables["user_id"]).toBe("1");
    expect(variables["user_name"]).toBe("Alex");
    expect(variables["call_reason"]).toBe("inbound");
    expect(variables["ride_summary"]).toBe("");
  });

  it("matches the greeting the phone webhook sends for the same person", () => {
    // voice.initiation builds "Hi {name}, this is Eco from eCARide. Do you want to book a ride,
    // or check on one?" so the web session and the phone call open the same way.
    const phone = "Hi Alex, this is Eco from eCARide. Do you want to book a ride, or check on one?";
    expect(agentVariables({ id: 1, name: "Alex" } as SessionUser)["greeting"]).toBe(phone);
  });

  it("never leaves a variable undefined, whatever the session looks like", () => {
    for (const user of [null, undefined, { id: 9, name: "", email: "", role: "rider" }]) {
      const variables = agentVariables(user as SessionUser | null | undefined);
      expect(Object.keys(variables).sort()).toEqual([...REQUIRED].sort());
      for (const name of REQUIRED) {
        expect(variables[name]).toBeTypeOf("string");
        expect(variables[name]).not.toBeUndefined();
      }
    }
  });

  it("waits for the session before starting, so a click mid-request is not greeted as a stranger", () => {
    mocks.agent = { agent_id: "agent_123", phone: "" };
    mocks.pending = true;
    const { rerender } = render(<TalkToAgent />);
    fireEvent.click(screen.getByRole("button", { name: "Talk to Eco" }));
    expect(document.querySelector("elevenlabs-convai")).toBeNull();
    expect(screen.getByRole("button", { name: "Getting Eco ready" })).toBeInTheDocument();

    mocks.pending = false;
    mocks.user = { id: 2, name: "Maya", email: "maya@eride.demo", role: "rider" };
    rerender(<TalkToAgent />);
    expect(mountedVariables()["user_name"]).toBe("Maya");
  });

  it("remounts with fresh variables when the user signs in or out", () => {
    mocks.agent = { agent_id: "agent_123", phone: "" };
    const { rerender } = render(<TalkToAgent />);
    fireEvent.click(screen.getByRole("button", { name: "Talk to Eco" }));
    expect(mountedVariables()["user_id"]).toBe("");

    mocks.user = { id: 4, name: "Sam", email: "sam@eride.demo", role: "owner" };
    rerender(<TalkToAgent />);
    expect(document.querySelectorAll("elevenlabs-convai")).toHaveLength(1);
    expect(mountedVariables()["user_id"]).toBe("4");
    expect(mountedVariables()["user_name"]).toBe("Sam");

    mocks.user = null;
    rerender(<TalkToAgent />);
    expect(document.querySelectorAll("elevenlabs-convai")).toHaveLength(1);
    expect(mountedVariables()["user_id"]).toBe("");
    expect(mountedVariables()["greeting"]).not.toContain("Sam");
  });
});
