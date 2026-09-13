import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGES = ["/", "/verify", "/judges"];

for (const path of PAGES) {
  test(`no serious or critical accessibility violations on ${path}`, async ({ page }) => {
    await page.goto(path);

    // The home page shows a preloader first; audit the page a visitor actually uses.
    if (path === "/") {
      await expect(page.getByRole("status", { name: "Loading PriceQuorum" })).toHaveCount(0, { timeout: 20_000 });
      await expect(page.getByRole("button", { name: /start the run/i })).toBeVisible();
    }

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    const summary = blocking.map((v) => `${v.id} (${v.impact}, ${v.nodes.length} nodes): ${v.help}`).join("\n");
    expect(blocking, summary).toEqual([]);
  });
}
