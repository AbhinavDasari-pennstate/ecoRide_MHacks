// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  vite: {
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: process.env["BACKEND_URL"] ?? "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/api/, ""),
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq, req) => {
              proxyReq.removeHeader("forwarded");
              proxyReq.removeHeader("x-real-ip");
              proxyReq.removeHeader("x-forwarded-for");
              proxyReq.setHeader(
                "x-forwarded-proto",
                "encrypted" in req.socket && req.socket.encrypted ? "https" : "http",
              );
              if (req.socket.remoteAddress) {
                proxyReq.setHeader("x-forwarded-for", req.socket.remoteAddress);
              }
            });
          },
          timeout: 65000,
          proxyTimeout: 65000,
        },
      },
    },
  },
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
});
