import { describe, expect, it } from "vitest";

import { readHealth } from "@/lib/api/client";

const HEALTHY = { ok: true, version: "1.0.0", commit_sha: "abc1234", db: "ok", stripe_mode: "test", slack_socket: "connected" };

describe("readHealth", () => {
  it("reports healthy only when every part of the body says so", () => {
    expect(readHealth(HEALTHY)).toEqual({ state: "healthy" });
  });

  it("names what is down instead of trusting a 200", () => {
    expect(readHealth({ ...HEALTHY, db: "down" })).toEqual({ state: "degraded", problems: ["database not ok"] });
    expect(readHealth({ ...HEALTHY, slack_socket: "down", stripe_mode: "live" })).toEqual({
      state: "degraded",
      problems: ["Slack approvals not connected", "Stripe is not in test mode"],
    });
  });

  it("treats a body that is not the health JSON as degraded", () => {
    expect(readHealth(null).state).toBe("degraded");
    expect(readHealth("<html>fallback page</html>").state).toBe("degraded");
    expect(readHealth({}).state).toBe("degraded");
  });
});
