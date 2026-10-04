import { useEffect, useRef, useState } from "react";
import { Mic, Phone } from "lucide-react";
import { useSession, useVoiceAgent, type SessionUser } from "@/lib/account-api";

const WIDGET_SRC = "https://unpkg.com/@elevenlabs/convai-widget-embed";

/**
 * Every variable the agent's first message and prompt use, kept in step with PLACEHOLDERS in
 * backend/app/voice.py. A phone call gets these from the /voice/initiation webhook, but a web
 * session starts straight at ElevenLabs, so the widget has to supply them itself. A missing one
 * ends the session before it starts, which is why none of these is ever left undefined.
 *
 * system__caller_id is not here on purpose: ElevenLabs fills that in, and it is empty on the web.
 */
export function agentVariables(user: SessionUser | null | undefined): Record<string, string> {
  const generic = "Hi, this is Eco from eCARide. Do you want to book a ride, or check on one?";
  return {
    greeting: user
      ? `Hi ${user.name}, this is Eco from eCARide. Do you want to book a ride, or check on one?`
      : generic,
    call_reason: "inbound",
    user_id: user ? String(user.id) : "",
    user_name: user ? user.name : "",
    ride_summary: "",
  };
}

/** +16282779064 reads as "+1 628-277-9064". Anything else is shown as given. */
export function formatPhone(e164: string): string {
  const digits = e164.replace(/\D/g, "");
  if (!(e164.startsWith("+1") && digits.length === 11)) return e164;
  const area = digits.slice(1, 4);
  return `+1 ${area}-${digits.slice(4, 7)}-${digits.slice(7)}`;
}

/**
 * "Talk to Eco": mounts the ElevenLabs web widget on demand so the landing page never loads a
 * third-party script until someone asks for it. The Twilio number is the fallback on phones.
 */
export function TalkToAgent() {
  const agent = useVoiceAgent().data;
  const session = useSession();
  const [open, setOpen] = useState(false);
  const slot = useRef<HTMLDivElement>(null);
  const agentId = agent?.agent_id;
  // A failed /auth/me means signed out, not broken: the landing page works with the API down.
  const settled = !session.isPending;
  const user = session.data?.user ?? null;
  // Serialising here makes this the effect's dependency, so signing in or out remounts the widget
  // with fresh variables instead of leaving a stale name or id in a live session.
  const variables = JSON.stringify(agentVariables(user));

  useEffect(() => {
    // Wait for the session before mounting, or a click made while /auth/me is still in flight
    // would start a session that greets a signed-in person as a stranger.
    if (!open || !agentId || !slot.current || !settled) return;
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
    widget.setAttribute("dynamic-variables", variables);
    slot.current.append(widget);
    return () => widget.remove();
  }, [open, agentId, settled, variables]);

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
          {open
            ? settled
              ? "Eco is ready at the bottom right"
              : "Getting Eco ready"
            : "Talk to Eco"}
        </button>
      )}
      {agent?.phone && (
        <a className="account-muted inline-flex items-center gap-2" href={`tel:${agent.phone}`}>
          <Phone size={15} />
          or call {formatPhone(agent.phone)}
        </a>
      )}
      <div ref={slot} />
    </div>
  );
}
