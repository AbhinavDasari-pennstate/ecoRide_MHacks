import { Bell, MessageSquare, Smartphone } from "lucide-react";
import { campusDay, campusTime } from "@/lib/backend";
import type { RideNotification } from "@/lib/account-api";

const HEADING: Record<RideNotification["notice"], string> = {
  proposed: "We found you a ride",
  confirmed: "Your ride is confirmed",
  vehicle_changed: "Your ride changed car",
};

/**
 * Ride notices for the signed-in account. These are recorded whether or not a text went out, so
 * the details are always visible here even when the phone network cannot carry them.
 */
export function Notifications({ items }: { items: RideNotification[] }) {
  if (!items.length) return null;
  return (
    <section className="account-panel mb-5" aria-labelledby="profile-notifications">
      <p className="account-eyebrow">Updates</p>
      <h2 id="profile-notifications" className="mt-1 flex items-center gap-2 text-xl font-semibold">
        <Bell className="size-5 text-primary" />
        Notifications
      </h2>
      <ul className="mt-5 divide-y divide-border">
        {items.map((item) => (
          <li key={item.id} className="flex items-start gap-3 py-4">
            <span className="mt-0.5 shrink-0 text-muted-foreground" aria-hidden="true">
              {item.delivered === "sms" ? (
                <Smartphone className="size-4" />
              ) : (
                <MessageSquare className="size-4" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-semibold">{HEADING[item.notice]}</p>
              <p className="account-muted mt-1 text-sm leading-relaxed">{item.text}</p>
              <p className="account-muted mt-1 text-xs">
                {campusDay(item.ts)}, {campusTime(item.ts)}
                {item.delivered === "sms" ? ", sent by text" : ", shown here only"}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
