import { useEffect, useRef } from "react";
import { ChevronLeft } from "lucide-react";
import { useStore, userById } from "@/lib/store";
import { handleAction, perform } from "@/lib/api";
import type { Message } from "@/lib/store";
import { cn } from "@/lib/utils";
import { LogoMark } from "./Logo";

const EMPTY_MESSAGES: Message[] = [];
export function Phone({ userId }: { userId: string }) {
  const msgs = useStore((s) => s.messages[userId] ?? EMPTY_MESSAGES);
  const busy = useStore((s) => s.busy);
  const typing = useStore((s) => s.typing[userId]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [msgs.length, typing]);
  const u = userById(userId);
  const last = msgs[msgs.length - 1];
  return (
    <div className="mx-auto h-[600px] w-[310px] shrink-0 rounded-[48px] bg-phone p-2.5 shadow-float">
      <div className="relative flex h-full flex-col overflow-hidden rounded-[40px] bg-card">
        <div className="mx-auto mt-2 h-6 w-24 rounded-full bg-phone" />
        <div className="flex items-center justify-between px-6 pt-1 text-[11px] font-semibold">
          <span>9:41</span>
          <span>{u.name.split(" ")[0]}'s phone</span>
        </div>
        <div className="flex flex-col items-center border-b border-border pb-2 pt-2">
          <div className="flex w-full items-center px-3">
            <ChevronLeft className="size-5 text-imessage" />
          </div>
          <div className="-mt-4 grid size-11 place-items-center rounded-full border border-border bg-card">
            <LogoMark className="size-9" />
          </div>
          <div className="mt-1 text-[11px] font-medium">ERIDE</div>
        </div>
        <div className="flex-1 space-y-1.5 overflow-y-auto px-3 py-3">
          {msgs.length === 0 && !typing && (
            <div className="pt-10 text-center text-xs text-muted-foreground">No messages yet</div>
          )}
          {msgs.map((m, i) => (
            <div
              key={m.id}
              className={cn(
                "flex animate-fade-in flex-col",
                m.from === "me" ? "items-end" : "items-start",
              )}
            >
              <div
                className={cn(
                  "max-w-[82%] rounded-[18px] px-3 py-2 text-[13.5px] leading-snug",
                  m.from === "me" ? "bg-imessage text-white" : "bg-bubble text-foreground",
                )}
              >
                {m.text}
              </div>
              {m.from === "me" && i === msgs.length - 1 && (
                <div className="mt-0.5 text-[10px] text-muted-foreground">Delivered</div>
              )}
            </div>
          ))}
          {typing && (
            <div className="flex w-14 gap-1 rounded-[18px] bg-bubble px-3 py-3">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="animate-dot size-2 rounded-full bg-muted-foreground"
                  style={{ animationDelay: `${i * 0.2}s` }}
                />
              ))}
            </div>
          )}
          <div ref={end} />
        </div>
        {last?.actions && (
          <div className="flex flex-wrap justify-center gap-2 px-3 pb-2">
            {last.actions.map((a) => (
              <button
                key={a}
                disabled={busy}
                onClick={() => void perform(() => handleAction(userId, a))}
                className="animate-pop rounded-full border border-imessage px-4 py-1.5 text-xs font-bold text-imessage transition hover:bg-imessage hover:text-white disabled:opacity-40"
              >
                {a}
              </button>
            ))}
          </div>
        )}
        <div className="m-2 rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground">
          Message simulation · live booking actions
        </div>
      </div>
    </div>
  );
}
