"use client";

import { useEffect, useState } from "react";

import { CopyHash } from "@/components/ui/CopyHash";
import { API_BASE } from "@/lib/api/client";
import { parseLedgerExport, tamperCopy, verifyLedger, type ChainVerification, type LedgerExport } from "@/lib/verify/chain";

type LoadState =
  | { kind: "loading" }
  | { kind: "unconfigured" }
  | { kind: "unreachable"; detail: string }
  | { kind: "invalid"; reasons: string[] }
  | { kind: "ready"; exported: LedgerExport; result: ChainVerification };

type Tampered = { entryId: number; field: string; result: ChainVerification } | null;

function Verdict({ result }: { result: ChainVerification }) {
  const trusted = result.chainIntact && result.headMatches && result.signatureValid !== false;
  return (
    <div
      role="status"
      className={`rounded-md px-5 py-4 text-lg font-semibold ${trusted ? "bg-outcome-success text-paper-light" : "bg-outcome-refused text-paper-light"}`}
    >
      {trusted
        ? `Chain intact: ${result.entries} entries recomputed in this browser${result.signatureValid ? ", head signature valid" : ""}.`
        : result.firstBadId !== null
          ? `Tampering detected at entry ${result.firstBadId}.`
          : !result.headMatches
            ? "The published head does not match the recomputed chain."
            : "The head signature does not verify."}
    </div>
  );
}

export function LedgerVerifier() {
  const [state, setState] = useState<LoadState>(() => (API_BASE ? { kind: "loading" } : { kind: "unconfigured" }));
  const [tampered, setTampered] = useState<Tampered>(null);

  useEffect(() => {
    if (!API_BASE) return;
    let cancelled = false;
    (async () => {
      let body: unknown;
      try {
        const res = await fetch(`${API_BASE}/api/ledger/export`, { cache: "no-store" });
        if (!res.ok) {
          if (!cancelled) setState({ kind: "unreachable", detail: `The backend answered with status ${res.status}.` });
          return;
        }
        body = await res.json();
      } catch {
        if (!cancelled) setState({ kind: "unreachable", detail: `The ledger export at ${API_BASE} is not reachable.` });
        return;
      }
      const parsed = parseLedgerExport(body);
      if (!parsed.ok) {
        if (!cancelled) setState({ kind: "invalid", reasons: parsed.reasons });
        return;
      }
      const result = await verifyLedger(parsed.value);
      if (!cancelled) setState({ kind: "ready", exported: parsed.value, result });
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const runTamper = async () => {
    if (state.kind !== "ready" || state.exported.rows.length === 0) return;
    const middle = state.exported.rows[Math.floor(state.exported.rows.length / 2)];
    const { copy, field } = tamperCopy(state.exported, middle.id);
    setTampered({ entryId: middle.id, field, result: await verifyLedger(copy) });
  };

  return (
    <section className="texture-paper relative z-[var(--z-content)] w-full max-w-[960px] rounded-[10px] px-6 py-8 text-ink shadow-[0_30px_60px_-30px_rgb(0_0_0/0.65)] sm:px-10">
      <h1 className="type-display text-[clamp(1.8rem,4vw,3rem)] uppercase text-ink [text-shadow:0.04em_0.05em_0_rgb(217_205_173)]">
        Check the ledger yourself
      </h1>
      <p className="mt-3 max-w-[64ch] leading-relaxed text-ink-soft">
        This page downloads the ledger and recomputes every entry hash in your browser (SHA-256 over the RFC 8785
        canonical payload, chained from 32 zero bytes), then checks the Ed25519 signature on the head. The verdict
        reported by the server is not used.
      </p>

      <div className="mt-6">
        {state.kind === "loading" ? <p className="text-ink-soft">Downloading the ledger export.</p> : null}
        {state.kind === "unconfigured" ? (
          <p role="alert" className="font-semibold text-outcome-needs-human">
            The web app does not know where the backend runs, so there is no ledger to check yet.
          </p>
        ) : null}
        {state.kind === "unreachable" ? (
          <p role="alert" className="font-semibold text-outcome-needs-human">
            {state.detail} Try again once the backend is online.
          </p>
        ) : null}
        {state.kind === "invalid" ? (
          <div role="alert" className="text-outcome-refused">
            <p className="font-semibold">The export cannot be verified:</p>
            <ul className="mt-2 list-disc pl-5">
              {state.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {state.kind === "ready" ? (
          <div className="space-y-6">
            <Verdict result={state.result} />

            <dl className="grid gap-2 text-sm sm:grid-cols-[9rem_minmax(0,1fr)]">
              <dt className="text-ink-soft">Entries</dt>
              <dd>{state.result.entries}</dd>
              <dt className="text-ink-soft">Recomputed head</dt>
              <dd>
                <CopyHash value={state.result.computedHead} label="recomputed head" />
              </dd>
              <dt className="text-ink-soft">Published head</dt>
              <dd>
                <CopyHash value={state.exported.head} label="published head" />
              </dd>
              <dt className="text-ink-soft">Public key</dt>
              <dd>
                <CopyHash value={state.exported.publicKey} label="ledger public key" />
              </dd>
              <dt className="text-ink-soft">Signature</dt>
              <dd>
                {state.result.signatureValid === null
                  ? "not published"
                  : state.result.signatureValid
                    ? "valid for this head and key"
                    : "does not verify"}
              </dd>
            </dl>

            {state.result.problems.length > 0 ? (
              <ul className="list-disc pl-5 text-sm text-outcome-refused">
                {state.result.problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            ) : null}

            <div className="rounded-md border border-ink/15 bg-paper-light/70 p-4">
              <p className="font-semibold">Try to cheat</p>
              <p className="mt-1 text-sm text-ink-soft">
                Change one character inside one entry of a copy held in this browser, then verify that copy. The ledger on
                the server is not touched.
              </p>
              <div className="mt-3 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={runTamper}
                  disabled={state.exported.rows.length === 0}
                  className="cursor-pointer rounded-md bg-forest px-4 py-2 font-semibold text-paper-light transition-colors duration-200 hover:bg-olive disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Edit one entry and re-verify
                </button>
                {tampered ? (
                  <button
                    type="button"
                    onClick={() => setTampered(null)}
                    className="cursor-pointer rounded-md border border-ink/30 px-4 py-2 font-semibold transition-colors duration-200 hover:bg-ink/5"
                  >
                    Discard the edited copy
                  </button>
                ) : null}
              </div>
              {tampered ? (
                <div className="mt-4 space-y-2">
                  <p className="text-sm">
                    Changed field <span className="type-hash">{tampered.field}</span> in entry {tampered.entryId}.
                  </p>
                  <Verdict result={tampered.result} />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
