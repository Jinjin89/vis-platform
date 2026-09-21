import { defineConfig } from "@playwright/test";

const localBypass = [process.env.NO_PROXY, "127.0.0.1", "localhost"]
  .filter(Boolean)
  .join(",");
process.env.NO_PROXY = localBypass;
process.env.no_proxy = localBypass;

export default defineConfig({
  testDir: "./browser-tests",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5178",
    viewport: { width: 1440, height: 900 },
    launchOptions: { args: ["--no-sandbox"] },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "../backend/.venv/bin/python ../backend/tests/browser_server.py",
      url: "http://127.0.0.1:18188/api/v1/health",
      reuseExistingServer: false,
      timeout: 20_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5178 --strictPort",
      url: "http://127.0.0.1:5178",
      reuseExistingServer: false,
      timeout: 20_000,
      env: {
        VIS_PLATFORM_BACKEND_ORIGIN: "http://127.0.0.1:18188",
        VITE_API_BASE: "",
      },
    },
  ],
});
