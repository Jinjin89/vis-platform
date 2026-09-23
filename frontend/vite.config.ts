import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // Loaded on demand by Pinpoint; prebundled so the dev server does not reload mid-session.
  optimizeDeps: { include: ["@deck.gl/core", "@deck.gl/layers"] },
  server: {
    host: "0.0.0.0",
    proxy: {
      "/api":
        process.env.VIS_PLATFORM_BACKEND_ORIGIN ?? "http://localhost:18080",
    },
  },
  test: {
    include: ["tests/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    css: true,
  },
});
