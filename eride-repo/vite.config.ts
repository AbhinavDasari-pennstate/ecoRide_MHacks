// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";
import { loadEnv } from "vite";
import { fileURLToPath } from "node:url";

// Only the dev server reads this token; it is never exposed as a VITE_* variable.
const backendEnv = loadEnv(
  "development",
  fileURLToPath(new URL("../backend", import.meta.url)),
  "API_SERVICE_TOKEN",
);

export default defineConfig({
  vite: {
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: process.env["BACKEND_URL"] ?? "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/api/, ""),
          headers: backendEnv["API_SERVICE_TOKEN"]
            ? { Authorization: `Bearer ${backendEnv["API_SERVICE_TOKEN"]}` }
            : {},
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
