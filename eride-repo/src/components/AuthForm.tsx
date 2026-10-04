import { useState, type FormEvent } from "react";
import { Link, Navigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Leaf } from "lucide-react";
import {
  accountHome,
  accountRequest,
  allowedPage,
  useSession,
  type SessionUser,
} from "@/lib/account-api";

export function safeNext(value: unknown): string {
  return typeof value === "string" &&
    /^(\/(?:profile|owner|buyer)?|\/trip\/(?:1|2|3|done)(?:\?trip=\d+)?)$/.test(value)
    ? value
    : "/";
}
export function AuthForm({ signup, next }: { signup: boolean; next: string }) {
  const session = useSession(),
    client = useQueryClient();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  if (session.data?.user && !busy) return <Navigate to={accountHome(session.data.user)} replace />;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const body = {
        email: String(form.get("email")).trim(),
        password: String(form.get("password")),
        ...(signup
          ? { name: String(form.get("name")).trim(), role: String(form.get("role")) }
          : {}),
      };
      const result = await accountRequest<{ user: SessionUser }>(
        signup ? "/auth/signup" : "/auth/login",
        { method: "POST", body },
      );
      await client.cancelQueries();
      client.clear();
      client.setQueryData(["session"], result);
      const destination = safeNext(next);
      window.location.assign(
        destination !== "/" && allowedPage(destination.split("?")[0]!, result.user.role)
          ? destination
          : accountHome(result.user),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Please try again.");
      setBusy(false);
    }
  }
  return (
    <main className="auth-layout">
      <aside className="auth-story">
        <Leaf size={32} strokeWidth={1.5} />
        <p className="account-eyebrow">eCARide</p>
        <h2>
          Campus
          <br />
          ride sharing
        </h2>
        <p>Book rides or manage your vehicle listings.</p>
        <div className="auth-story-bottom">
          <span>Riders</span>
          <span>Car owners</span>
          <span>Data buyers</span>
        </div>
      </aside>
      <section className="auth-form-panel">
        <p className="account-eyebrow">{signup ? "Sign up" : "Welcome back"}</p>
        <h1>{signup ? "Create your account" : "Sign in to eCARide"}</h1>
        <p className="account-muted">
          {signup ? "Use your email and a password." : "Sign in to access your account."}
        </p>
        <form onSubmit={(event) => void submit(event)} className="account-form">
          {signup && (
            <label className="account-label">
              Full name
              <input
                name="name"
                className="account-input"
                autoComplete="name"
                required
                maxLength={120}
              />
            </label>
          )}
          <label className="account-label">
            Email address
            <input
              name="email"
              className="account-input"
              type="email"
              autoComplete="email"
              required
              maxLength={254}
            />
          </label>
          <label className="account-label">
            Password
            <input
              name="password"
              className="account-input"
              type="password"
              autoComplete={signup ? "new-password" : "current-password"}
              minLength={signup ? 12 : 1}
              maxLength={128}
              required
            />
            {signup && <span className="account-field-note">Use at least 12 characters.</span>}
          </label>
          {signup && (
            <label className="account-label">
              I'm here to
              <select
                name="role"
                className="account-input"
                defaultValue={next === "/owner" ? "owner" : "rider"}
              >
                <option value="rider">Book shared trips</option>
                <option value="owner">Share my car and book trips</option>
              </select>
            </label>
          )}
          {error && (
            <p role="alert" className="account-error">
              {error}
            </p>
          )}
          <button className="account-button w-full" disabled={busy} type="submit">
            {busy ? "Please wait…" : signup ? "Create account" : "Sign in"}
            <ArrowRight size={16} />
          </button>
        </form>
        <p className="auth-switch">
          {signup ? "Already have an account?" : "New to eCARide?"}{" "}
          <Link to={signup ? "/login" : "/signup"} search={{ next }}>
            {signup ? "Sign in" : "Create an account"}
          </Link>
        </p>
        <p className="account-field-note mt-6">
          Data buyers sign in with an account approved by the eCARide team.
        </p>
      </section>
    </main>
  );
}
