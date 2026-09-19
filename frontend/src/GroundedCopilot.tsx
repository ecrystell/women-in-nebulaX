import { useEffect, useState } from "react";

import { railAccessApi, RailAccessApiError } from "./api/client";
import type { CopilotMode, CopilotResponse, RunView } from "./api/types";

type CopilotAnswers = {
  activity_explanation: Record<string, CopilotResponse>;
  capacity_hotspots?: CopilotResponse;
  handover_summary?: CopilotResponse;
};

/** A deliberately action-only UI: no free-text schedule or disruption requests. */
export function GroundedCopilot({ run }: { run: RunView | null }) {
  const [open, setOpen] = useState(false);
  const [activityId, setActivityId] = useState("");
  const [mode, setMode] = useState<CopilotMode>("activity_explanation");
  const [answers, setAnswers] = useState<CopilotAnswers>({ activity_explanation: {} });
  const [requestingMode, setRequestingMode] = useState<CopilotMode | null>(null);
  const [notice, setNotice] = useState("");
  const activityIds = Array.from(new Set(run?.schedule?.placements.map((placement) => placement.activity_id) ?? [])).sort();
  const busy = requestingMode !== null;
  const answer = mode === "activity_explanation"
    ? answers.activity_explanation[activityId]
    : answers[mode];

  // Answers are tied to a single generated schedule, never the previous run.
  useEffect(() => {
    setAnswers({ activity_explanation: {} });
    setActivityId("");
    setNotice("");
  }, [run?.schedule?.schedule_id]);

  const ask = async () => {
    if (!run?.schedule || busy) return;
    const requestedMode = mode;
    const requestedActivityId = activityId;
    if (requestedMode === "activity_explanation" && !requestedActivityId) {
      setNotice("Select a scheduled activity first.");
      return;
    }
    setRequestingMode(requestedMode);
    setNotice("");
    try {
      const response = await railAccessApi.createCopilotResponse(
        run.run_id,
        requestedMode,
        requestedMode === "activity_explanation" ? requestedActivityId : undefined
      );
      setAnswers((current) => requestedMode === "activity_explanation"
        ? {
            ...current,
            activity_explanation: {
              ...current.activity_explanation,
              [requestedActivityId]: response
            }
          }
        : { ...current, [requestedMode]: response });
    } catch (error) {
      setNotice(error instanceof RailAccessApiError ? error.message : "The grounded copilot is unavailable.");
    } finally {
      setRequestingMode(null);
    }
  };

  return (
    <div className="fixed bottom-4 right-4 z-30 sm:bottom-5 sm:right-5">
      {open && (
        <section className="flex max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-md flex-col overflow-hidden rounded-2xl border border-red-300/25 bg-slate-950/95 shadow-2xl shadow-red-950/60 backdrop-blur-xl sm:max-h-[min(42rem,calc(100vh-2.5rem))]">
          <div className="flex items-start justify-between border-b border-slate-800 px-4 py-3.5">
            <div className="flex min-w-0 items-center gap-3">
              <span aria-hidden="true" className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-red-300/25 bg-red-500/10 text-lg">🚇</span>
              <div>
                <p className="text-sm font-bold text-white">RailAccess Copilot</p>
                <p className="mt-0.5 text-xs text-slate-400">Evidence-backed schedule brief</p>
              </div>
            </div>
            <button className="rounded-lg px-2 py-1 text-xl leading-none text-slate-400 transition hover:bg-slate-800 hover:text-white" onClick={() => setOpen(false)} aria-label="Close copilot">×</button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <p className="text-sm leading-6 text-slate-300">Choose a concise, read-only explanation. The copilot cannot change the schedule or establish feasibility.</p>
            {!run?.schedule ? (
              <p className="mt-4 rounded-xl border border-slate-800 bg-slate-900/70 p-3 text-xs leading-5 text-slate-400">Run a schedule first to make its evidence available.</p>
            ) : (
              <div className="mt-4 space-y-4">
                <div className="grid grid-cols-3 gap-1 rounded-xl border border-slate-800 bg-slate-900/70 p-1" role="tablist" aria-label="Copilot request type">
                  {([
                    ["activity_explanation", "Activity"],
                    ["capacity_hotspots", "Hotspots"],
                    ["handover_summary", "Handover"]
                  ] as const).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      role="tab"
                      aria-selected={mode === value}
                      onClick={() => { setMode(value); setNotice(""); }}
                      className={`rounded-lg px-2 py-2 text-xs font-bold transition ${mode === value ? "bg-red-500 text-white shadow-sm" : "text-slate-400 hover:bg-slate-800 hover:text-slate-100"}`}
                    >{label}</button>
                  ))}
                </div>
                {mode === "activity_explanation" && (
                  <label className="block text-xs font-semibold text-slate-300">
                    Scheduled activity
                    <select value={activityId} onChange={(event) => setActivityId(event.target.value)} className="mt-1.5 w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2.5 text-sm text-white outline-none focus:border-red-400">
                      <option value="">Select an activity</option>
                      {activityIds.map((id) => <option key={id} value={id}>{id}</option>)}
                    </select>
                  </label>
                )}
                <button disabled={busy || (mode === "activity_explanation" && !activityId)} onClick={() => void ask()} className="w-full rounded-xl bg-red-500 px-3 py-2.5 text-sm font-bold text-white shadow-lg shadow-red-950/35 transition hover:bg-red-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400">
                  {requestingMode === mode ? "Preparing grounded response…" : mode === "activity_explanation" ? "Explain activity" : mode === "capacity_hotspots" ? "Show capacity hotspots" : "Create handover brief"}
                </button>
              </div>
            )}
            {notice && <p role="alert" className="mt-3 rounded-xl border border-rose-400/30 bg-rose-400/10 p-3 text-xs leading-5 text-rose-100">{notice}</p>}
            {!answer && run?.schedule && !notice && (
              <div className="mt-4 rounded-xl border border-dashed border-slate-700 bg-slate-900/45 px-4 py-5 text-center text-sm leading-6 text-slate-400">
                {mode === "activity_explanation"
                  ? "Choose an activity, then ask for a plain-language explanation."
                  : mode === "capacity_hotspots"
                    ? "This view is ready for a fresh capacity-pressure brief."
                    : "This view is ready for a fresh shift-handover brief."}
              </div>
            )}
            {answer && (
              <article className="mt-4 overflow-hidden rounded-xl border border-slate-700 bg-slate-900/85">
                <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.12em] text-red-200"><span>{answer.mode.replaceAll("_", " ")}</span><span>Grounded</span></div>
                <div className="max-h-60 overflow-y-auto px-3 py-3 text-sm leading-6 text-slate-200"><p>{answer.answer}</p></div>
                <div className="border-t border-slate-800 bg-slate-950/50 px-3 py-2.5 text-[11px] leading-4 text-amber-100">{answer.verification_disclaimer}</div>
                <p className="px-3 py-2 text-[11px] text-slate-500">Evidence v{answer.evidence.evidence_version} · schedule {answer.evidence.schedule_id.slice(0, 8)}</p>
              </article>
            )}
          </div>
          <div className="border-t border-slate-800 bg-slate-950/70 px-4 py-3 text-[11px] leading-4 text-slate-500">
            Selected evidence is sent server-side to Gemini. Raw CSVs, exports and organiser reports stay in RailAccess.
          </div>
        </section>
      )}
      {!open && (
        <button onClick={() => setOpen(true)} className="group flex items-center gap-2 rounded-full border border-red-200/40 bg-slate-950/90 px-4 py-3 shadow-lg shadow-red-950/60 backdrop-blur transition hover:-translate-y-1 hover:border-red-200" aria-label="Open RailAccess Copilot">
          <span className="text-2xl transition group-hover:translate-x-0.5">🚇</span><span className="text-left text-xs font-bold uppercase tracking-[0.14em] text-red-100">Ask copilot</span>
        </button>
      )}
    </div>
  );
}
