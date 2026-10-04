import { useEffect, useState } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { Wordmark } from "./Logo";
import { PwaInstall } from "./PwaInstall";
import { accountHome, accountRequest, allowedPage, useSession } from "@/lib/account-api";

export function Shell() {
  const location = useLocation(),
    session = useSession(),
    client = useQueryClient(),
    navigate = useNavigate();
  const user = session.data?.user;
  const [signingOut, setSigningOut] = useState(false),
    [error, setError] = useState("");
  const isPublic = ["/", "/login", "/signup"].includes(location.pathname.replace(/\/$/, "") || "/");
  useEffect(() => {
    const expire = () => {
      void client.cancelQueries();
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" });
      client.setQueryData(["session"], { user: null });
    };
    window.addEventListener("eride-session-expired", expire);
    return () => window.removeEventListener("eride-session-expired", expire);
  }, [client]);
  useEffect(() => {
    if (session.data?.user === null) {
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" });
    }
  }, [client, session.data?.user]);
  async function signOut() {
    setSigningOut(true);
    setError("");
    try {
      await accountRequest("/auth/logout", { method: "POST" });
      await client.cancelQueries();
      client.clear();
      client.setQueryData(["session"], { user: null });
      await navigate({ to: "/" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Couldn't sign out. Try again.");
    } finally {
      setSigningOut(false);
    }
  }
  let content = <Outlet />;
  if (!isPublic) {
    if (session.isPending)
      content = (
        <main className="account-page" role="status">
          Checking your account…
        </main>
      );
    else if (session.error)
      content = (
        <main className="account-page">
          <div className="account-panel">
            <h1>Let's reconnect</h1>
            <p className="account-muted">{session.error.message}</p>
            <button className="account-button" onClick={() => void session.refetch()}>
              Try again
            </button>
          </div>
        </main>
      );
    else if (!user) content = <Navigate to="/login" search={{ next: location.href }} replace />;
    else if (!allowedPage(location.pathname, user.role))
      content = (
        <main className="account-page">
          <div className="account-panel">
            <h1>This page needs a different account</h1>
            <p className="account-muted">
              You're signed in as a {user.role}. Only approved accounts can open this area.
            </p>
            <Link className="account-button" to={accountHome(user)}>
              Go to my home
            </Link>
          </div>
        </main>
      );
  }
  return (
    <div className="flex min-h-screen flex-col">
      <header className="account-header">
        <Link to="/" aria-label="ERIDE">
          <Wordmark />
        </Link>
        <nav aria-label="Main navigation">
          {user ? (
            <>
              {user.role !== "buyer" && (
                <Link to="/profile" activeProps={{ className: "is-active" }}>
                  My trips
                </Link>
              )}
              {user.role === "owner" && (
                <Link to="/owner" activeProps={{ className: "is-active" }}>
                  My cars
                </Link>
              )}
              {user.role === "buyer" && (
                <Link to="/buyer" activeProps={{ className: "is-active" }}>
                  Data Portal
                </Link>
              )}
              <span className="account-user" title={user.email}>
                {user.name.split(" ")[0]}
              </span>
              <button onClick={() => void signOut()} disabled={signingOut} aria-label="Sign out">
                <LogOut size={16} />
                <span>{signingOut ? "Signing out…" : "Sign out"}</span>
              </button>
            </>
          ) : (
            <>
              <Link to="/login" search={{ next: "/" }}>
                Sign in
              </Link>
              <Link to="/signup" search={{ next: "/" }} className="account-signup-link">
                Create account
              </Link>
            </>
          )}
        </nav>
      </header>
      {error && (
        <div role="alert" className="account-error mx-6">
          {error}
        </div>
      )}
      {content}
      <PwaInstall />
    </div>
  );
}
