import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight, Check, Leaf, MapPin, Users, Wallet } from "lucide-react";
import { LogoMark } from "@/components/Logo";
import { TalkToAgent } from "@/components/TalkToAgent";
import { useCampusImpact, useSession } from "@/lib/account-api";
export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Book a trip | ERIDE" },
      {
        name: "description",
        content:
          "Book a shared campus trip. Split the cost and choose a lower-emissions way to get there.",
      },
    ],
  }),
  component: Home,
});
export function Home() {
  const user = useSession().data?.user;
  return (
    <main className="ride-home">
      <section className="ride-home-hero">
        <div className="ride-home-copy">
          <p className="account-eyebrow">Ann Arbor</p>
          <h1>Book a trip.</h1>
          <p className="ride-home-intro">
            Choose your pickup and destination to find a shared campus ride.
          </p>
          {user?.role === "buyer" ? (
            <Link to="/buyer" className="account-button ride-book-button">
              Open Data Portal <ArrowRight size={19} />
            </Link>
          ) : (
            <Link
              to="/trip/$step"
              params={{ step: "1" }}
              search={{ trip: undefined }}
              className="account-button ride-book-button"
            >
              Book a trip <ArrowRight size={19} />
            </Link>
          )}
          <p className="ride-home-note">
            <Check size={13} /> See your match and estimated price before you confirm.
          </p>
          <TalkToAgent />
          <div className="ride-home-benefits">
            <span>
              <Wallet size={18} /> Shared costs
            </span>
            <span>
              <Leaf size={18} /> CO₂ estimates
            </span>
            <span>
              <Users size={18} /> Campus pickups
            </span>
          </div>
        </div>
        <div className="ride-route-card">
          <div className="ride-route-top">
            <span>Campus rides</span>
            <Leaf size={20} />
          </div>
          <div className="ride-route-art" aria-hidden="true">
            <svg viewBox="0 0 440 270">
              <path
                d="M-10 75H145Q195 75 195 125V180Q195 230 255 230H450"
                className="ride-road-edge"
              />
              <path
                d="M-10 75H145Q195 75 195 125V180Q195 230 255 230H450"
                className="ride-road-line"
              />
              <circle cx="90" cy="75" r="13" />
              <circle cx="343" cy="230" r="13" />
            </svg>
            <div className="ride-route-stop ride-route-stop-start">
              <MapPin size={14} /> Your campus
            </div>
            <div className="ride-route-stop ride-route-stop-end">
              <MapPin size={14} /> Your next stop
            </div>
            <div className="ride-route-car">
              <LogoMark className="size-28" />
            </div>
            <span className="ride-route-person person-one">You</span>
            <span className="ride-route-person person-two">+1</span>
            <span className="ride-route-person person-three">+1</span>
          </div>
          <div className="ride-route-caption">
            <h2>Shared route</h2>
            <p>We look for compatible trips and a lower-emissions vehicle for the group.</p>
          </div>
        </div>
      </section>
      <CampusImpact />
      <section className="ride-how" aria-labelledby="ride-how-title">
        <div>
          <p className="account-eyebrow">Booking</p>
          <h2 id="ride-how-title">How it works</h2>
        </div>
        <div className="ride-how-grid">
          {[
            {
              title: "Trip details",
              text: "Choose your pickup, destination, and departure time.",
            },
            {
              title: "Review your match",
              text: "Review a compatible group, vehicle, and estimated cost.",
            },
            {
              title: "Confirm your place",
              text: "Each traveler confirms, then the car owner approves the booking.",
            },
          ].map((item, i) => (
            <article key={item.title}>
              <span>0{i + 1}</span>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="ride-owner-invite">
        <div>
          <h2>List your car</h2>
          <p>Set availability and approve booking requests.</p>
        </div>
        {user?.role === "owner" ? (
          <Link to="/owner">
            Share your car <ArrowRight size={17} />
          </Link>
        ) : user ? (
          <p>Vehicle listings are available to owner accounts.</p>
        ) : (
          <Link to="/signup" search={{ next: "/owner" }}>
            Share your car <ArrowRight size={17} />
          </Link>
        )}
      </section>
      <footer className="ride-home-footer">
        <span>ERIDE</span>
        <p>Campus ride sharing</p>
        <span>Ann Arbor</span>
      </footer>
    </main>
  );
}

const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
function CampusImpact() {
  const impact = useCampusImpact().data;
  if (!impact?.trips) return null;
  const stats: [string, string][] = [
    [impact.kg_co2_avoided.toFixed(1), "kg CO₂ avoided"],
    [whole.format(impact.miles_avoided), "car miles avoided"],
    [whole.format(impact.trips), "trips shared"],
    [`${Math.round(impact.ev_share * 100)}%`, "of groups in an EV"],
  ];
  return (
    <section className="ride-impact" aria-labelledby="ride-impact-title">
      <p className="account-eyebrow">Campus so far</p>
      <h2 id="ride-impact-title">What sharing has saved</h2>
      <div className="ride-impact-grid">
        {stats.map(([value, label]) => (
          <div key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <p className="ride-impact-note">
        About {impact.equivalents.tree_seedlings_10yr} tree seedlings growing for ten years, or{" "}
        {whole.format(impact.equivalents.smartphone_charges)} smartphone charges. {impact.basis}.
        Emission factors from the EPA.
      </p>
    </section>
  );
}
