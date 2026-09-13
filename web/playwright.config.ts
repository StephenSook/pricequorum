import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end checks run against a real deployment. BASE_URL defaults to production so
 * the suite tests what a visitor actually receives.
 */
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "https://pricequorum-web.vercel.app",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
