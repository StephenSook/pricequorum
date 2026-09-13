import { describe, expect, it } from "vitest";

import { cuesBetween, snapshotOf } from "@/components/sound/useSoundCue";
import { initialRunView, reduceRun, type Envelope } from "@/lib/api/events";

const RUN = "3f7c1a52-0000-4000-8000-000000000001";
const PROOF = { chain_head: "a".repeat(64), signature: "b".repeat(128), public_key: "c".repeat(64), invariants_expected: ["prices_agree"] };
const envelope = (seq: number, type: string, payload: Record<string, unknown>): Envelope => ({ seq, runId: RUN, type, at: "t", payload });
const apply = (...events: Envelope[]) => events.reduce(reduceRun, initialRunView(RUN));

describe("cuesBetween", () => {
  it("plays nothing for the first snapshot, only announces where the run is", () => {
    const view = apply(envelope(1, "ledger.pending", { ledger_id: 7, step_no: 1, app: "stripe" }));
    expect(cuesBetween(null, snapshotOf(view))).toEqual({ cues: [], announcement: "Writing the change to the apps, one ledger step at a time." });
    expect(cuesBetween(null, snapshotOf(null))).toEqual({ cues: [], announcement: null });
  });

  it("plays a paper cue on a new chapter and a chain cue when a ledger step completes", () => {
    const before = snapshotOf(apply(envelope(1, "approval.requested", { summary: "Pro 20 to 25", mode: "slack" })));
    const pending = snapshotOf(
      apply(envelope(1, "approval.requested", { summary: "Pro 20 to 25", mode: "slack" }), envelope(2, "ledger.pending", { ledger_id: 7, step_no: 1 })),
    );
    expect(cuesBetween(before, pending).cues).toEqual(["paper"]);

    const completed = snapshotOf(
      apply(
        envelope(1, "approval.requested", { summary: "Pro 20 to 25", mode: "slack" }),
        envelope(2, "ledger.pending", { ledger_id: 7, step_no: 1 }),
        envelope(3, "ledger.completed", { ledger_id: 7, entry_hash: "bb" }),
      ),
    );
    expect(cuesBetween(pending, completed)).toEqual({ cues: ["chain"], announcement: null });
  });

  it("stamps only when a valid outcome arrives and names it plainly", () => {
    const verify = snapshotOf(apply(envelope(1, "invariant.result", { name: "prices_agree", ok: true, outcome: "SUCCESS" })));
    const done = snapshotOf(
      apply(envelope(1, "invariant.result", { name: "prices_agree", ok: true, outcome: "SUCCESS" }), envelope(2, "run.outcome", { outcome: "SUCCESS", ...PROOF })),
    );
    expect(cuesBetween(verify, done)).toEqual({ cues: ["stamp"], announcement: "The backend reported the outcome: success." });

    const rejected = snapshotOf(
      apply(envelope(1, "invariant.result", { name: "prices_agree", ok: true, outcome: "SUCCESS" }), envelope(2, "run.outcome", { outcome: "SUCCESS" })),
    );
    expect(cuesBetween(verify, rejected).cues).toEqual([]);
  });
});
