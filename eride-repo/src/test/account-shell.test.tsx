import { act, cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Shell } from "@/components/Shell";
import { accountRequest, type SessionUser } from "@/lib/account-api";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function show(path: string, role: SessionUser["role"] | null, unavailable = false) {
  vi.stubGlobal(
    "fetch",
    unavailable
      ? vi.fn().mockRejectedValue(new Error("offline"))
      : vi.fn().mockResolvedValue(
          new Response(
            JSON.stringify({
              user: role ? { id: 41, name: "Taylor", email: "taylor@example.test", role } : null,
            }),
            { status: 200 },
          ),
        ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRootRoute({
    component: () => (
      <QueryClientProvider client={client}>
        <Shell />
      </QueryClientProvider>
    ),
  });
  const routes = [
    createRoute({
      getParentRoute: () => root,
      path: "/",
      component: () => <main>Book a trip</main>,
    }),
    createRoute({
      getParentRoute: () => root,
      path: "/login",
      component: () => <main>Sign in to continue</main>,
    }),
    createRoute({
      getParentRoute: () => root,
      path: "/buyer",
      component: () => <main>Private insights</main>,
    }),
    createRoute({
      getParentRoute: () => root,
      path: "/owner",
      component: () => <main>My car listings</main>,
    }),
  ];
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  await router.load();
  render(<RouterProvider router={router} />);
  return client;
}

describe("Account access", () => {
  it("shows the book-trip landing page even when the account server is offline", async () => {
    await show("/", null, true);
    expect(await screen.findByText("Book a trip")).toBeInTheDocument();
  });
  it("redirects signed-out visitors before showing buyer content", async () => {
    await show("/buyer", null);
    expect(await screen.findByText("Sign in to continue")).toBeInTheDocument();
    expect(screen.queryByText("Private insights")).not.toBeInTheDocument();
  });
  it("blocks riders from buyer pages and omits buyer navigation", async () => {
    await show("/buyer", "rider");
    expect(await screen.findByText("This page needs a different account")).toBeInTheDocument();
    expect(screen.queryByText("Private insights")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Data Portal" })).not.toBeInTheDocument();
  });
  it("opens the owner interface for an owner", async () => {
    await show("/owner", "owner");
    expect(await screen.findByText("My car listings")).toBeInTheDocument();
  });
  it("removes private pages and cached data as soon as a session expires", async () => {
    const client = await show("/owner", "owner");
    expect(await screen.findByText("My car listings")).toBeInTheDocument();
    client.setQueryData(["dashboard", 41], { trips: ["private trip"] });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(
            new Response(JSON.stringify({ detail: "Authentication required" }), { status: 401 }),
          ),
        ),
    );
    await act(async () => {
      await accountRequest("/users/41/dashboard").catch(() => undefined);
    });
    expect(await screen.findByText("Sign in to continue")).toBeInTheDocument();
    expect(screen.queryByText("My car listings")).not.toBeInTheDocument();
    expect(client.getQueryData(["dashboard", 41])).toBeUndefined();
  });
});
