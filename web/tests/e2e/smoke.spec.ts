import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Every judge-facing route, loaded in a real browser. A route passes only when its main content
 * is visible and its JavaScript runs without an uncaught error or a hydration failure.
 */
const ROUTES: { path: string; ready: (page: Page) => Locator; status?: number }[] = [
  // The preloader only leaves once the client bundle has run, so this proves JavaScript executed.
  { path: "/", ready: (page) => page.getByRole("button", { name: /start the run/i }) },
  { path: "/verify", ready: (page) => page.getByRole("heading", { name: /check the ledger yourself/i }) },
  { path: "/evals", ready: (page) => page.getByRole("heading", { name: /the evidence/i }) },
  { path: "/judges", ready: (page) => page.getByRole("heading", { name: /a three-minute tour/i }) },
  { path: "/runs/3f7c1a52-0000-4000-8000-000000000001", ready: (page) => page.getByRole("status").first() },
  { path: "/this-page-does-not-exist", ready: (page) => page.getByRole("heading", { name: /no page here/i }), status: 404 },
];

for (const route of ROUTES) {
  test(`${route.path} loads and runs its JavaScript without errors`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`uncaught: ${err.message}`));
    page.on("console", (message) => {
      if (message.type() === "error" && /hydrat/i.test(message.text())) errors.push(`hydration: ${message.text()}`);
    });

    const response = await page.goto(route.path);
    expect(response?.status()).toBe(route.status ?? 200);
    await expect(route.ready(page)).toBeVisible({ timeout: 20_000 });
    expect(errors).toEqual([]);
  });
}
