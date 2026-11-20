import { existsSync } from "node:fs";
import { loadEnvConfig } from "@next/env";
import { defineConfig, devices } from "@playwright/test";

// frontend/.env, as Next reads it: the tests import lib/ code that reads
// NEXT_PUBLIC_PROJECT_SLUG (the cookie names).
loadEnvConfig(process.cwd());

// The mock login provider comes with backend/modules/oauth; without that
// module there is nothing to start (and e2e/oauth.spec.ts skips itself).
const oauth = existsSync("../backend/modules/oauth");

// Runs against `make dev` if it is already up; otherwise starts the backend,
// the frontend and (with modules/oauth) the mock login provider.
// In CI the servers are always started fresh.
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run python manage.py runserver 8000",
      cwd: "../backend",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: !process.env.CI,
      // Off by default; on here for e2e/signup.spec.ts (modules/signup).
      env: { AUTH_SIGNUP: "True", AUTH_PASSWORD_RESET: "True" },
    },
    ...(oauth
      ? [
          {
            command: "uv run python manage.py oauth_mock",
            cwd: "../backend",
            port: 8001,
            reuseExistingServer: !process.env.CI,
          },
        ]
      : []),
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      // The test of the Admin link needs it (there is no .env in CI).
      env: { DJANGO_ADMIN_URL: "http://localhost:8000/admin/" },
    },
  ],
});
