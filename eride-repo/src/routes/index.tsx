import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { useSession } from "@/lib/account-api";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Book a trip | ERIDE" },
      { name: "description", content: "Book a shared campus ride and split the cost." },
    ],
  }),
  component: Home,
});

export function Home() {
  const user = useSession().data?.user;
  const buyer = user?.role === "buyer";
  return (
    <main className="ride-home">
      <h1>{buyer ? "Data Portal" : "Book a trip"}</h1>
      <p className="account-muted">
        {buyer
          ? "Explore the simulated driving dataset."
          : "Shared rides around Ann Arbor. Split the cost and reduce solo trips."}
      </p>
      <div className="ride-home-actions">
        {buyer ? (
          <Link to="/buyer" className="account-button">
            Open Data Portal <ArrowRight size={18} />
          </Link>
        ) : (
          <Link
            to="/trip/$step"
            params={{ step: "1" }}
            search={{ trip: undefined }}
            className="account-button"
          >
            Book a trip <ArrowRight size={18} />
          </Link>
        )}
        {user?.role === "owner" ? (
          <Link to="/owner" className="ride-home-secondary">
            Manage cars
          </Link>
        ) : !user ? (
          <Link to="/signup" search={{ next: "/owner" }} className="ride-home-secondary">
            List your car
          </Link>
        ) : null}
      </div>
    </main>
  );
}
