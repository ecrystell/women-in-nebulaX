import { useMemo, useState } from "react";

import type { CapabilityReport, RunView, ScenarioChangeDraft, ScenarioChangeDraftUpdate } from "./api/types";

type DraftProps = {
  draft: ScenarioChangeDraft;
  run: RunView;
  busy: boolean;
  recoveryAvailable: boolean;
  onUpdate: (payload: ScenarioChangeDraftUpdate) => Promise<ScenarioChangeDraft>;
  onConfirm: (draftId: string) => Promise<void>;
  onReplay: (draftId: string) => Promise<void>;
};

function ReviewDraft({ draft, run, busy, recoveryAvailable, onUpdate, onConfirm, onReplay }: DraftProps) {
  const [current, setCurrent] = useState(draft);
  const [placementFilter, setPlacementFilter] = useState("");
  const [notice, setNotice] = useState("");
  const groups = useMemo(() => {
    const result = new Map<string, { capacity: number; weeks: number[] }>();
    current.change.supply_overrides.forEach((item) => {
      const group = result.get(item.location_id) ?? { capacity: item.supply_capacity, weeks: [] };
      group.capacity = item.supply_capacity;
      group.weeks.push(item.week);
      result.set(item.location_id, group);
    });
    return [...result.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [current]);
  const updateGroup = (locationId: string, capacity: number, selected: number[]) => {
    const unchanged = current.change.supply_overrides.filter((item) => item.location_id !== locationId);
    setCurrent({ ...current, change: { ...current.change, supply_overrides: [...unchanged, ...selected.map((week) => ({ location_id: locationId, week, supply_capacity: capacity }))] } });
  };
  const toggleLock = (activityId: string, accessSeq: number) => {
    const exists = current.change.locked_placements.some((item) => item.activity_id === activityId && item.access_seq === accessSeq);
    setCurrent({ ...current, change: { ...current.change, locked_placements: exists ? current.change.locked_placements.filter((item) => item.activity_id !== activityId || item.access_seq !== accessSeq) : [...current.change.locked_placements, { activity_id: activityId, access_seq: accessSeq }] } });
  };
  const save = async () => {
    setNotice("");
    try {
      setCurrent(await onUpdate({ supply_overrides: current.change.supply_overrides, locked_placements: current.change.locked_placements, rationale: current.change.rationale }));
      setNotice("Review changes saved and checked.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not save this recovery review."); }
  };
  const visiblePlacements = (run.schedule?.placements ?? []).filter((item) => `${item.activity_id} ${item.access_seq}`.toLowerCase().includes(placementFilter.toLowerCase()));
  const horizon = Math.max(1, ...current.change.supply_overrides.map((item) => item.week));

  return <div className="mt-4 space-y-4 rounded-2xl border border-cyan-300/30 bg-slate-900/75 p-4 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-bold text-white">Recovery review</p><p className="text-xs text-slate-400">Source: {current.source.replace("_", " ")} · Base schedule: {current.change.base_schedule_id}</p></div><span className={`rounded-full px-3 py-1 text-xs font-bold ${current.status === "ready" ? "bg-emerald-400/15 text-emerald-200" : "bg-amber-300/15 text-amber-100"}`}>{current.status === "ready" ? "Ready for review" : "Needs review"}</span></div>
    <div className="space-y-3 border-t border-slate-700 pt-3"><p className="font-bold text-white">Changed supply</p>{groups.map(([locationId, group]) => <div key={locationId} className="grid gap-2 rounded-xl border border-slate-700 p-3 lg:grid-cols-[1fr_8rem_1.4fr]"><label className="text-xs text-slate-300"><span className="mb-1 block font-bold text-white">{locationId}</span>Capacity</label><input aria-label={`${locationId} capacity`} type="number" min="0" value={group.capacity} onChange={(event) => updateGroup(locationId, Number(event.target.value), group.weeks)} className="rounded-lg border border-slate-600 bg-slate-950 px-2 py-1.5 text-white" /><label className="text-xs text-slate-300">Affected weeks<select aria-label={`${locationId} weeks`} multiple value={group.weeks.map(String)} onChange={(event) => updateGroup(locationId, group.capacity, [...event.target.selectedOptions].map((option) => Number(option.value)))} className="mt-1 h-20 w-full rounded-lg border border-slate-600 bg-slate-950 px-2 py-1 text-white">{Array.from({ length: horizon }, (_, index) => index + 1).map((week) => <option key={week} value={week}>Week {week}</option>)}</select></label></div>)}</div>
    <div className="border-t border-slate-700 pt-3"><p className="font-bold text-white">Lock approved baseline work</p><input value={placementFilter} onChange={(event) => setPlacementFilter(event.target.value)} placeholder="Find activity or access sequence" className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white" /><div className="mt-2 max-h-44 overflow-y-auto rounded-xl border border-slate-700 bg-slate-950/60 p-2">{visiblePlacements.map((item) => { const locked = current.change.locked_placements.some((lock) => lock.activity_id === item.activity_id && lock.access_seq === item.access_seq); return <label key={`${item.activity_id}-${item.access_seq}`} className="flex cursor-pointer items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-xs hover:bg-slate-800"><span>{item.activity_id} · access {item.access_seq} · week {item.week}</span><input type="checkbox" checked={locked} onChange={() => toggleLock(item.activity_id, item.access_seq)} /></label>; })}</div></div>
    <label className="block border-t border-slate-700 pt-3 text-xs text-slate-300">Controller rationale<textarea value={current.change.rationale ?? ""} onChange={(event) => setCurrent({ ...current, change: { ...current.change, rationale: event.target.value } })} maxLength={500} className="mt-1 min-h-16 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white" /></label>
    {[...current.unresolved_references, ...current.field_errors.map((item) => `${item.field}: ${item.message}`)].map((item) => <p key={item} className="text-xs text-amber-100">{item}</p>)}
    <div className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => void save()} className="rounded-lg border border-cyan-300/40 px-3 py-2 text-xs font-bold text-cyan-100 disabled:text-slate-500">Save review changes</button>{run.demo ? <button disabled={busy || current.status !== "ready"} onClick={() => void onReplay(current.draft_id)} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:bg-slate-700">Replay fixed public example</button> : <button disabled={busy || current.status !== "ready" || !recoveryAvailable} onClick={() => void onConfirm(current.draft_id)} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:bg-slate-700">Confirm and re-optimise</button>}</div>
    {!run.demo && !recoveryAvailable && <p className="text-xs text-amber-100">This draft is saved for review. Re-optimisation is unavailable until the recovery solver is connected.</p>}{notice && <p role="alert" className="text-xs text-cyan-100">{notice}</p>}
  </div>;
}

export function RecoverySandbox({ run, capabilities, busy, onOpenDemo, onReplay, onCreateDraft, onCreateSupplyDraft, onUpdateDraft, onConfirmDraft }: {
  run: RunView | null; capabilities: CapabilityReport | null; busy: boolean; onOpenDemo: () => Promise<void>; onReplay: (draftId?: string) => Promise<void>; onCreateDraft: (text: string) => Promise<ScenarioChangeDraft>; onCreateSupplyDraft: (file: File) => Promise<ScenarioChangeDraft>; onUpdateDraft: (draftId: string, payload: ScenarioChangeDraftUpdate) => Promise<ScenarioChangeDraft>; onConfirmDraft: (draftId: string) => Promise<void>;
}) {
  const [request, setRequest] = useState(""); const [supplyFile, setSupplyFile] = useState<File | null>(null); const [draft, setDraft] = useState<ScenarioChangeDraft | null>(null); const [notice, setNotice] = useState(""); const isDemo = run?.demo === true;
  const createCsvDraft = async () => { if (!supplyFile) return; try { setDraft(await onCreateSupplyDraft(supplyFile)); setNotice(""); } catch (error) { setNotice(error instanceof Error ? error.message : "Could not review this supply CSV."); } };
  const parse = async () => { if (!request.trim()) return; try { setDraft(await onCreateDraft(request.trim())); setNotice(""); } catch (error) { setNotice(error instanceof Error ? error.message : "The public demo parser is unavailable."); } };
  return <section className="editorial-card mt-5 rounded-2xl border border-cyan-300/25 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur"><p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">Recovery sandbox</p><h2 className="mt-1 text-xl font-bold text-white">Disruption review, safely staged</h2>{!run ? <div className="mt-3 text-sm text-slate-300"><p>Run a schedule first, or open the public fixture to explore the review workflow.</p><button disabled={!capabilities?.public_demo_recovery.available || busy} onClick={() => void onOpenDemo()} className="mt-3 rounded-xl border border-cyan-300/40 px-4 py-2 font-bold text-cyan-100 disabled:text-slate-500">Open public recovery demo</button></div> : <div className="mt-4 space-y-4">{isDemo && <div className="rounded-xl border border-amber-300/35 bg-amber-300/10 p-3 text-xs text-amber-50">{run.demo_notice ?? "Public demonstration fixture — not a newly optimised schedule."}</div>}<div className="rounded-xl border border-slate-700 bg-slate-900/65 p-3"><p className="font-bold text-white">Upload replacement supply data</p><p className="mt-1 text-xs text-slate-400">Upload an edited official <code>04_LOCATION_SUPPLY.csv</code>. Only capacity changes are accepted; they initially apply to every planning week.</p><input type="file" accept=".csv,text/csv" onChange={(event) => setSupplyFile(event.target.files?.[0] ?? null)} className="mt-3 block text-xs text-slate-300" /><button disabled={!supplyFile || busy} onClick={() => void createCsvDraft()} className="mt-2 rounded-lg border border-cyan-300/40 px-3 py-2 text-xs font-bold text-cyan-100 disabled:text-slate-500">Create CSV review draft</button></div>{isDemo ? <div className="border-t border-slate-800 pt-4"><p className="font-bold text-white">Describe a disruption</p><p className="mt-1 text-xs text-slate-400">Gemini parses only the public fixture’s bounded identifiers. It cannot change or validate a schedule.</p><textarea value={request} onChange={(event) => setRequest(event.target.value)} maxLength={1000} className="mt-2 min-h-20 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-white" placeholder="Reduce capacity and keep an access fixed." /><button disabled={!capabilities?.disruption_drafts.available || busy || !request.trim()} onClick={() => void parse()} className="mt-2 rounded-lg border border-cyan-300/40 px-3 py-2 text-xs font-bold text-cyan-100 disabled:text-slate-500">Create AI review draft</button></div> : <p className="text-xs text-slate-500">Natural-language parsing is intentionally limited to the public demo. Hidden uploaded data is never sent to Gemini.</p>}{draft && <ReviewDraft draft={draft} run={run} busy={busy} recoveryAvailable={capabilities?.recovery.available ?? false} onUpdate={(payload) => onUpdateDraft(draft.draft_id, payload)} onConfirm={(draftId) => onConfirmDraft(draftId)} onReplay={(draftId) => onReplay(draftId)} />}{notice && <p role="alert" className="text-xs text-amber-100">{notice}</p>}</div>}</section>;
}
