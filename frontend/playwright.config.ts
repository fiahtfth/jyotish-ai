import { defineConfig, devices } from "@playwright/test";
import path from "path";

const root = path.resolve(__dirname, "..");
const port = Number(process.env.E2E_PORT || 8001);
const py = process.env.E2E_PYTHON || path.join(root, "backend/.venv/bin/python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: `http://127.0.0.1:${port}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // Fresh DB on every run; serves the already-built frontend/out.
    command: `rm -f /tmp/jyotish_e2e.db && ${py} -m uvicorn app.main:app --host 127.0.0.1 --port ${port}`,
    cwd: path.join(root, "backend"),
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      JYOTISH_FRONTEND_DIR: path.join(root, "frontend/out"),
      JYOTISH_DATABASE_URL: "sqlite:////tmp/jyotish_e2e.db",
      JYOTISH_LLM_PROVIDER: "offline",
      JYOTISH_JWT_SECRET: "e2e-test-secret-0123456789-abcdefghijkl",
    },
  },
});
