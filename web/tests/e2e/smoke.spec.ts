import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Every judge-facing route, loaded in a real browser. A route passes only when React has
 * hydrated it (proved by a marker a client component sets), its main content is visible, and
 * after the network settles there is no uncaught error, no console error, and no failed
 * same-origin script, style, font or image.
 */
const ROUTES: { path: string; ready: (page: Page) => Locator; status?: number }[] = [
  { path: "/", ready: (page) => page.getByRole("button", { name: /start the run/i }) },
  { path: "/verify", ready: (page) => page.getByRole("heading", { name: /check the ledger yourself/i }) },
  { path: "/evals", ready: (page) => page.getByRole("heading", { name: /the evidence/i }) },
  { path: "/judges", ready: (page) => page.getByRole("heading", { name: /a three-minute tour/i }) },
  { path: "/runs/3f7c1a52-0000-4000-8000-000000000001", ready: (page) => page.getByRole("status").first() },
  { path: "/this-page-does-not-exist", ready: (page) => page.getByRole("heading", { name: /no page here/i }), status: 404 },
];

// Requests to the backend may fail while it is down; each page reports that state itself.
const BACKEND_NOISE = /Failed to load resource|EventSource/i;

for (const route of ROUTES) {
  test(`${route.path} hydrates and runs its JavaScript without errors`, async ({ page, baseURL }) => {
    const origin = new URL(baseURL ?? "http://localhost").origin;
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`uncaught: ${err.message}`));
    page.on("console", (message) => {
      if (message.type() === "error" && !BACKEND_NOISE.test(message.text())) errors.push(`console: ${message.text()}`);
    });
    page.on("requestfailed", (request) => {
      const reason = request.failure()?.errorText ?? "";
      if (request.url().startsWith(origin) && !reason.includes("ERR_ABORTED")) errors.push(`request failed: ${request.url()} ${reason}`);
    });
    page.on("response", (response) => {
      const kind = response.request().resourceType();
      if (response.url().startsWith(origin) && response.status() >= 400 && ["script", "stylesheet", "font", "image"].includes(kind)) {
        errors.push(`${response.status()} ${kind}: ${response.url()}`);
      }
    });

    const response = await page.goto(route.path);
    expect(response?.status()).toBe(route.status ?? 200);
    await expect(page.locator("html[data-hydrated='true']")).toHaveCount(1, { timeout: 20_000 });
    await expect(route.ready(page)).toBeVisible({ timeout: 20_000 });
    await page.waitForLoadState("networkidle");
    expect(errors).toEqual([]);
  });
}
