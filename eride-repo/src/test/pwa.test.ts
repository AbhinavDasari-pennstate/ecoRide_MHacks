import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";

function worker() {
  const handlers = new Map<string, (event: unknown) => void>();
  const stored = new Map<string, Map<string, Response>>();
  let online = true;
  const networkRequests: string[] = [];
  runInNewContext(readFileSync(resolve("public/sw.js"), "utf8"), {
    URL,
    Response,
    self: {
      location: { origin: "https://eride.example" },
      addEventListener: (name: string, handler: (event: unknown) => void) =>
        handlers.set(name, handler),
      clients: { claim: async () => {} },
    },
    caches: {
      open: async (name: string) => {
        if (!stored.has(name)) stored.set(name, new Map());
        const entries = stored.get(name)!;
        return {
          addAll: async (urls: string[]) => {
            for (const url of urls) entries.set(url, new Response(`Public asset: ${url}`));
          },
          match: async (url: string) => entries.get(url)?.clone(),
        };
      },
      keys: async () => [...stored.keys()],
      delete: async (name: string) => stored.delete(name),
    },
    fetch: async (request: { url: string }) => {
      networkRequests.push(request.url);
      if (!online) throw new TypeError("Network unavailable");
      return new Response("Private account page");
    },
  });
  return {
    stored,
    networkRequests,
    goOffline: () => {
      online = false;
    },
    lifecycle: async (name: string) => {
      let completion: Promise<unknown> | undefined;
      handlers.get(name)!({
        waitUntil: (promise: Promise<unknown>) => {
          completion = promise;
        },
      });
      await completion;
    },
    request: (path: string, method = "GET", mode = "navigate") => {
      let response: Promise<Response> | undefined;
      handlers.get("fetch")!({
        request: { url: new URL(path, "https://eride.example").href, method, mode },
        respondWith: (promise: Promise<Response>) => {
          response = promise;
        },
      });
      return response;
    },
  };
}

describe("PWA privacy and offline behavior", () => {
  it("never intercepts API calls, POSTs, subresources, or other origins", () => {
    const sw = worker();
    for (const [path, method, mode] of [
      ["/api", "GET", "navigate"],
      ["/api/account", "GET", "navigate"],
      ["/api/bookings", "POST", "cors"],
      ["/book", "POST", "navigate"],
      ["/assets/app.js", "GET", "cors"],
      ["https://other.example/", "GET", "navigate"],
    ]) {
      expect(sw.request(path!, method, mode)).toBeUndefined();
    }
    expect(sw.networkRequests).toEqual([]);
  });

  it("uses the network for private pages without caching them, then shows the public offline page", async () => {
    const sw = worker();
    await sw.lifecycle("install");
    const cachedUrls = [...sw.stored.values()].flatMap((cache) => [...cache.keys()]);
    expect(cachedUrls).toContain("/offline.html");
    expect(
      cachedUrls.every(
        (url) => url === "/offline.html" || url === "/favicon.svg" || url.startsWith("/icons/"),
      ),
    ).toBe(true);
    const onlineResponse = await sw.request("/profile");
    expect(await onlineResponse!.text()).toBe("Private account page");
    expect(sw.networkRequests).toEqual(["https://eride.example/profile"]);
    expect([...sw.stored.values()].flatMap((cache) => [...cache.keys()])).toEqual(cachedUrls);
    sw.goOffline();
    const offlineResponse = await sw.request("/book");
    expect(await offlineResponse!.text()).toBe("Public asset: /offline.html");
  });

  it("removes only old ERIDE public caches and handles a missing offline asset", async () => {
    const sw = worker();
    await sw.lifecycle("install");
    const activeCache = [...sw.stored.keys()][0]!;
    sw.stored.set("eride-public-obsolete", new Map());
    sw.stored.set("another-app-cache", new Map());
    await sw.lifecycle("activate");
    expect([...sw.stored.keys()]).toEqual([activeCache, "another-app-cache"]);
    sw.stored.get(activeCache)!.delete("/offline.html");
    sw.goOffline();
    const response = await sw.request("/");
    expect(response!.status).toBe(503);
    expect(await response!.text()).toMatch(/reconnect/i);
  });
});
