import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TalkToAgent, formatPhone } from "@/components/TalkToAgent";

const mocks = vi.hoisted(() => ({
  agent: undefined as { agent_id: string; phone: string } | undefined,
}));
vi.mock("@/lib/account-api", () => ({ useVoiceAgent: () => ({ data: mocks.agent }) }));
afterEach(() => {
  cleanup();
  document.querySelector("script[src*='convai-widget-embed']")?.remove();
});

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
