import { useState } from "react";

import { railAccessApi, RailAccessApiError } from "./api/client";
import type { CopilotMode, CopilotResponse, RunView } from "./api/types";

/** A deliberately action-only UI: no free-text schedule or disruption requests. */
export function GroundedCopilot({ run }: { run: RunView | null }) {
  const [open, setOpen] = useState(false);
  const [activityId, setActivityId] = useState("");
  const [answer, setAnswer] = useState<CopilotResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const activityIds = Array.from(new Set(run?.schedule?.placements.map((placement) => placement.activity_id) ?? [])).sort();

  const ask = async (mode: CopilotMode) => {
    if (!run?.schedule || busy) return;
    if (mode === "activity_explanation" && !activityId) {
      setNotice("Select a scheduled activity first.");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      setAnswer(await railAccessApi.createCopilotResponse(run.run_id, mode, activityId || undefined));
    } catch (error) {
      setNotice(error instanceof RailAccessApiError ? error.message : "The grounded copilot is unavailable.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed bottom-5 right-5 z-30">
      {open && (
        <section className="mb-3 w-80 rounded-2xl border border-red-400/30 bg-slate-950/95 p-4 shadow-2xl shadow-red-950/50 backdrop-blur">
          <div className="flex items-center justify-between">
            <div><p className="text-sm font-bold text-white">RailAccess Copilot</p><p className="text-xs text-red-200">Grounded schedule assistant</p></div>
            <button className="text-slate-400 hover:text-white" onClick={() => setOpen(false)} aria-label="Close copilot">×</button>
          </div>
          <p className="mt-4 text-sm leading-6 text-slate-300">Explain selected schedule evidence. It cannot modify a schedule or establish feasibility.</p>
          <p className="mt-2 text-[11px] leading-4 text-amber-100">Selected evidence is sent server-side to Gemini's global endpoint. Raw CSVs, exports and organiser reports remain in RailAccess.</p>
          {!run?.schedule ? <p className="mt-3 rounded-lg bg-slate-900 p-3 text-xs text-slate-400">Run a schedule first to make evidence available.</p> : (
            <div className="mt-4 space-y-2">
              <select value={activityId} onChange={(event) => setActivityId(event.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white">
                <option value="">Select activity for explanation</option>
                {activityIds.map((id) => <option key={id} value={id}>{id}</option>)}
              </select>
              <button disabled={busy} onClick={() => void ask("activity_explanation")} className="w-full rounded-lg border border-red-400/50 px-3 py-2 text-sm font-bold text-red-100 disabled:text-slate-500">Explain activity</button>
              <button disabled={busy} onClick={() => void ask("capacity_hotspots")} className="w-full rounded-lg border border-red-400/50 px-3 py-2 text-sm font-bold text-red-100 disabled:text-slate-500">Show hotspots</button>
              <button disabled={busy} onClick={() => void ask("handover_summary")} className="w-full rounded-lg border border-red-400/50 px-3 py-2 text-sm font-bold text-red-100 disabled:text-slate-500">Create handover</button>
            </div>
          )}
          {notice && <p className="mt-3 text-xs text-rose-200">{notice}</p>}
          {answer && <div className="mt-3 rounded-lg bg-slate-900 p-3 text-xs leading-5 text-slate-200"><p>{answer.answer}</p><p className="mt-2 text-amber-100">{answer.verification_disclaimer}</p><p className="mt-1 text-slate-500">Evidence v{answer.evidence.evidence_version} · schedule {answer.evidence.schedule_id.slice(0, 8)}</p></div>}
        </section>
      )}
      <button onClick={() => setOpen((value) => !value)} className="group flex h-15 items-center gap-2 rounded-full border border-red-200/40 bg-slate-950/90 px-4 py-3 shadow-lg shadow-red-950/60 backdrop-blur transition hover:-translate-y-1 hover:border-red-200" aria-label="Open RailAccess Copilot">
        <span className="text-2xl transition group-hover:translate-x-0.5">🚇</span><span className="text-left text-xs font-bold uppercase tracking-[0.14em] text-red-100">Ask copilot</span>
      </button>
    </div>
  );
}
