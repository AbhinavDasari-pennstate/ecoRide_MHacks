import { useEffect, useRef, useState } from "react";
import { Mic, Phone } from "lucide-react";
import { useVoiceAgent } from "@/lib/account-api";

const WIDGET_SRC = "https://unpkg.com/@elevenlabs/convai-widget-embed";

/**
 * "Talk to Eco": mounts the ElevenLabs web widget on demand so the landing page never loads a
 * third-party script until someone asks for it. The Twilio number is the fallback on phones.
 */
export function TalkToAgent() {
  const agent = useVoiceAgent().data;
  const [open, setOpen] = useState(false);
  const slot = useRef<HTMLDivElement>(null);
  const agentId = agent?.agent_id;

  useEffect(() => {
    if (!open || !agentId || !slot.current) return;
    if (!document.querySelector(`script[src="${WIDGET_SRC}"]`)) {
      const script = document.createElement("script");
      script.src = WIDGET_SRC;
      script.async = true;
      document.head.append(script);
    }
    // Create the element now; the custom element upgrades itself once the script arrives.
    const widget = document.createElement("elevenlabs-convai");
    widget.setAttribute("agent-id", agentId);
    widget.setAttribute("variant", "expanded");
    slot.current.append(widget);
    return () => widget.remove();
  }, [open, agentId]);

  if (!agentId && !agent?.phone) return null;
  return (
    <div className="mt-5 flex flex-wrap items-center gap-3 text-sm">
      {agentId && (
        <button
          type="button"
          className="account-secondary"
          onClick={() => setOpen(true)}
          disabled={open}
          aria-live="polite"
        >
          <Mic size={15} />
          {open ? "Eco is ready at the bottom right" : "Talk to Eco"}
        </button>
      )}
      {agent?.phone && (
        <a className="account-muted inline-flex items-center gap-2" href={`tel:${agent.phone}`}>
          <Phone size={15} />
          or call {agent.phone}
        </a>
      )}
      <div ref={slot} />
    </div>
  );
}
