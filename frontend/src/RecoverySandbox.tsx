import { useState } from "react";

import type { CapabilityReport, RunView, ScenarioChangeDraft } from "./api/types";

export function RecoverySandbox({
  run,
  capabilities,
  busy,
  onOpenDemo,
  onReplay,
  onCreateDraft
}: {
  run: RunView | null;
  capabilities: CapabilityReport | null;
  busy: boolean;
  onOpenDemo: () => Promise<void>;
  onReplay: (draftId?: string) => Promise<void>;
  onCreateDraft: (text: string) => Promise<ScenarioChangeDraft>;
}) {
  const [request, setRequest] = useState("");
  const [draft, setDraft] = useState<ScenarioChangeDraft | null>(null);
  const [notice, setNotice] = useState("");
  const demoAvailable = capabilities?.public_demo_recovery.available ?? false;
  const parserAvailable = capabilities?.disruption_drafts.available ?? false;
  const isDemo = run?.demo === true;
  const replay = async (draftId?: string) => {
    setNotice("");
    try {
      await onReplay(draftId);
      setNotice("Public replay loaded. It is a fixed fixture, not a new optimisation.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The public replay is unavailable.");
    }
  };
  const parse = async () => {
    if (!request.trim()) return;
    setNotice("");
    try {
      setDraft(await onCreateDraft(request.trim()));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The draft parser is unavailable.");
    }
  };

  return (
    <section className="editorial-card mt-5 rounded-2xl border border-cyan-300/25 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">Recovery sandbox</p>
      <h2 className="mt-1 text-xl font-bold text-white">Disruption review, safely staged</h2>
      {!isDemo ? (
        <div className="mt-3 space-y-3 text-sm leading-6 text-slate-300">
          <p>{capabilities?.recovery.message ?? "Checking recovery capability…"}</p>
          <button
            disabled={!demoAvailable || busy}
            onClick={() => void onOpenDemo()}
            className="rounded-xl border border-cyan-300/40 bg-cyan-300/10 px-4 py-2.5 font-bold text-cyan-100 transition hover:bg-cyan-300/20 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500"
          >
            Open public recovery demo
          </button>
          <p className="text-xs text-slate-500">{capabilities?.public_demo_recovery.message}</p>
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="rounded-xl border border-amber-300/35 bg-amber-300/10 p-3 text-sm leading-6 text-amber-50">
            {run.demo_notice ?? "Public demonstration fixture \u2014 not a newly optimised schedule."}
          </div>
          {run.scenario_change && (
            <div className="grid gap-3 rounded-xl border border-slate-700 bg-slate-900/65 p-3 text-xs text-slate-300 sm:grid-cols-3">
              <p><span className="block font-bold uppercase tracking-wide text-slate-500">Fixed change</span>{run.scenario_change.supply_overrides.length} supply reduction</p>
              <p><span className="block font-bold uppercase tracking-wide text-slate-500">Protected work</span>{run.scenario_change.locked_placements.length} locked placement</p>
              <p><span className="block font-bold uppercase tracking-wide text-slate-500">Local result</span>{run.validation_report?.status ?? "unavailable"}</p>
            </div>
          )}
          {run.schedule_diff && (
            <div className="grid gap-3 rounded-xl border border-slate-700 bg-slate-900/65 p-3 text-sm sm:grid-cols-2">
              <p><span className="block text-xs font-bold uppercase tracking-wide text-slate-500">Baseline → replay</span>{run.schedule_diff.unchanged_count} unchanged · {run.schedule_diff.moved_count} moved</p>
              <p><span className="block text-xs font-bold uppercase tracking-wide text-slate-500">Change budget</span>All declared locks are preserved in this replay.</p>
            </div>
          )}
          <button disabled={busy} onClick={() => void replay()} className="rounded-xl bg-cyan-500 px-4 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400">
            Replay fixed public recovery
          </button>

          <div className="border-t border-slate-800 pt-4">
            <p className="text-sm font-bold text-white">Describe a disruption</p>
            <p className="mt-1 text-xs leading-5 text-slate-400">The parser creates a review-only draft from public fixture IDs. It cannot change or validate a schedule.</p>
            <textarea value={request} onChange={(event) => setRequest(event.target.value)} maxLength={1000} placeholder="e.g. Reduce westbound platform capacity at H01 in week 8 to one, and keep A001 access 1 fixed." className="mt-3 min-h-24 w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300" />
            <button disabled={!parserAvailable || busy || !request.trim()} onClick={() => void parse()} className="mt-2 rounded-xl border border-cyan-300/40 px-4 py-2 text-sm font-bold text-cyan-100 transition hover:bg-cyan-300/10 disabled:cursor-not-allowed disabled:border-slate-700 disabled:text-slate-500">
              Create review draft
            </button>
            {!parserAvailable && <p className="mt-2 text-xs text-slate-500">{capabilities?.disruption_drafts.message}</p>}
          </div>
          {draft && (
            <div className="rounded-xl border border-slate-700 bg-slate-900/70 p-4 text-sm">
              <p className="font-bold text-white">Draft: {draft.status === "ready" ? "ready for review" : "needs review"}</p>
              <p className="mt-2 text-slate-300">{draft.change.supply_overrides.length} supply override(s) · {draft.change.locked_placements.length} placement lock(s)</p>
              {draft.assumptions.length > 0 && <p className="mt-2 text-xs text-slate-400">Assumptions: {draft.assumptions.join(" · ")}</p>}
              {[...draft.unresolved_references, ...draft.field_errors.map((item) => `${item.field}: ${item.message}`)].map((item) => <p key={item} className="mt-1 text-xs text-amber-100">{item}</p>)}
              <button disabled={busy || draft.status !== "ready"} onClick={() => void replay(draft.draft_id)} className="mt-3 rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400">Confirm and replay public fixture</button>
            </div>
          )}
          {notice && <p role="alert" className="rounded-xl border border-amber-300/30 bg-amber-300/10 p-3 text-xs leading-5 text-amber-100">{notice}</p>}
        </div>
      )}
    </section>
  );
}
