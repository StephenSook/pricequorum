import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Every judge-facing route, loaded in a real browser. A route passes only when its own client
 * component has mounted (a marker that component sets, in the route's own JavaScript chunk), its
 * main content is visible, and after the network settles there is no uncaught error, no
 * same-origin console error, and no failed same-origin script, style, font or image.
 */
const ROUTES: { path: string; marker: string | null; ready: (page: Page) => Locator; status?: number }[] = [
  { path: "/", marker: "home", ready: (page) => page.getByRole("button", { name: /start the run/i }) },
  { path: "/verify", marker: "verify", ready: (page) => page.getByRole("heading", { name: /check the ledger yourself/i }) },
  { path: "/evals", marker: "evals", ready: (page) => page.getByRole("heading", { name: /the evidence/i }) },
  { path: "/judges", marker: "judges", ready: (page) => page.getByRole("heading", { name: /a three-minute tour/i }) },
  { path: "/runs/3f7c1a52-0000-4000-8000-000000000001", marker: "run", ready: (page) => page.getByRole("status").first() },
  // The 404 page is a server component with no route chunk, so only the root marker applies.
  { path: "/this-page-does-not-exist", marker: null, ready: (page) => page.getByRole("heading", { name: /no page here/i }), status: 404 },
];

const ASSET_KINDS = ["script", "stylesheet", "font", "image"];

for (const route of ROUTES) {
  test(`${route.path} runs its own client code without errors`, async ({ page, baseURL }) => {
    const origin = new URL(baseURL ?? "http://localhost").origin;
    const documentUrl = new URL(route.path, origin).href;
    const errors: string[] = [];

    page.on("pageerror", (err) => errors.push(`uncaught: ${err.message}`));
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const url = message.location().url;
      // A request to the backend (another origin) may fail while it is down; the page reports that itself.
      if (url && !url.startsWith(origin)) return;
      // The 404 page's own document status is logged as a console error by the browser.
      if (route.status === 404 && url === documentUrl) return;
      errors.push(`console: ${message.text()} (${url || "no location"})`);
    });
    page.on("requestfailed", (request) => {
      if (!request.url().startsWith(origin)) return;
      const reason = request.failure()?.errorText ?? "";
      // Aborted prefetches are normal; an aborted asset never is.
      if (ASSET_KINDS.includes(request.resourceType()) || !reason.includes("ERR_ABORTED")) {
        errors.push(`request failed: ${request.resourceType()} ${request.url()} ${reason}`);
      }
    });
    page.on("response", (response) => {
      const kind = response.request().resourceType();
      if (response.url().startsWith(origin) && response.status() >= 400 && ASSET_KINDS.includes(kind)) {
        errors.push(`${response.status()} ${kind}: ${response.url()}`);
      }
    });

    const response = await page.goto(route.path);
    expect(response?.status()).toBe(route.status ?? 200);
    await expect(page.locator("html[data-hydrated='true']")).toHaveCount(1, { timeout: 20_000 });
    if (route.marker) {
      await expect(page.locator(`html[data-route-ready='${route.marker}']`)).toHaveCount(1, { timeout: 20_000 });
    }
    await expect(route.ready(page)).toBeVisible({ timeout: 20_000 });
    await page.waitForLoadState("networkidle");
    expect(errors).toEqual([]);
  });
}
