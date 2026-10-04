import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TalkToAgent } from "@/components/TalkToAgent";

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

  it("mounts the ElevenLabs widget on click and offers the phone number", () => {
    mocks.agent = { agent_id: "agent_123", phone: "+17345550199" };
    render(<TalkToAgent />);
    expect(screen.getByRole("link", { name: /call \+17345550199/ })).toHaveAttribute(
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
