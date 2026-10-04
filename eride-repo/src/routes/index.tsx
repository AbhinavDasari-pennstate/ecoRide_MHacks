import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight, Check, Leaf, MapPin, Users, Wallet } from "lucide-react";
import { LogoMark } from "@/components/Logo";
import { useSession } from "@/lib/account-api";
export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "ERIDE | Book a trip. Share the journey." },
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
          <p className="account-eyebrow">Small trips. A shared difference.</p>
          <h1>
            Book a trip.
            <br />
            <span>Go further, together.</span>
          </h1>
          <p className="ride-home-intro">
            The grocery run. The ride across campus. Share a car, split the cost, and leave a
            lighter footprint.
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
          <div className="ride-home-benefits">
            <span>
              <Wallet size={18} /> Share the cost
            </span>
            <span>
              <Leaf size={18} /> Fewer solo miles
            </span>
            <span>
              <Users size={18} /> Ride with your campus
            </span>
          </div>
        </div>
        <div className="ride-route-card">
          <div className="ride-route-top">
            <span>A shared way there</span>
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
            <h2>One car. More connection.</h2>
            <p>We look for compatible trips and a lower-emissions vehicle for the group.</p>
          </div>
        </div>
      </section>
      <section className="ride-how" aria-labelledby="ride-how-title">
        <div>
          <p className="account-eyebrow">From here to there</p>
          <h2 id="ride-how-title">A shared trip, in three steps.</h2>
        </div>
        <div className="ride-how-grid">
          {[
            {
              title: "Tell us where",
              text: "Choose your pickup, destination, and departure time.",
            },
            {
              title: "Find your people",
              text: "Review a compatible group, vehicle, and estimated cost.",
            },
            {
              title: "Confirm your place",
              text: "Everyone accepts. The car owner approves. You're set.",
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
          <h2>Have a car with time to spare?</h2>
          <p>Make it part of someone else's journey.</p>
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
        <p>Less driving alone. More moving together.</p>
        <span>Made for campus.</span>
      </footer>
    </main>
  );
}
