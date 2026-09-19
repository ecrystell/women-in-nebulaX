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

const lineNames: Record<string, string> = { ALP: "Alpha", BET: "Beta" };

function readableLocation(locationId: string) {
  const [kind, line, place, bound] = locationId.split(":");
  const kindName = kind === "PLAT" ? "Platform" : kind === "SEC" ? "Track section" : kind;
  const placeName = place ? place.replaceAll("_", " to ") : "location";
  const boundName = bound === "EB" ? "eastbound" : bound === "WB" ? "westbound" : bound;
  return `${kindName} · ${lineNames[line] ?? line} · ${placeName} · ${boundName}`;
}

function parseWeeks(value: string) {
  const weeks = new Set<number>();
  for (const segment of value.split(",").map((item) => item.trim()).filter(Boolean)) {
    const match = segment.match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!match) return null;
    const start = Number(match[1]);
    const end = Number(match[2] ?? match[1]);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start || end - start > 200) return null;
    for (let week = start; week <= end; week += 1) weeks.add(week);
  }
  return [...weeks].sort((left, right) => left - right);
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-slate-700 bg-slate-950/55 p-3"><p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</p><p className="mt-1 text-xl font-bold text-white">{value}</p><p className="text-xs text-slate-400">{detail}</p></div>;
}

function ReviewDraft({ draft, run, busy, recoveryAvailable, onUpdate, onConfirm, onReplay }: DraftProps) {
  const [current, setCurrent] = useState(draft);
  const [placementFilter, setPlacementFilter] = useState("");
  const [notice, setNotice] = useState("");
  const groups = useMemo(() => {
    const entries = new Map<string, { capacity: number; weeks: number[] }>();
    current.change.supply_overrides.forEach((item) => {
      const group = entries.get(item.location_id) ?? { capacity: item.supply_capacity, weeks: [] };
      group.capacity = item.supply_capacity;
      group.weeks.push(item.week);
      entries.set(item.location_id, group);
    });
    return [...entries.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [current]);
  const placements = (run.schedule?.placements ?? []).filter((item) => `${item.activity_id} ${item.access_seq}`.toLowerCase().includes(placementFilter.toLowerCase())).slice(0, 20);
  const issues = [...current.unresolved_references, ...current.field_errors.map((item) => `${item.field}: ${item.message}`)];
  const updateGroup = (locationId: string, capacity: number, weeks: number[]) => {
    const retained = current.change.supply_overrides.filter((item) => item.location_id !== locationId);
    setCurrent({ ...current, change: { ...current.change, supply_overrides: [...retained, ...weeks.map((week) => ({ location_id: locationId, week, supply_capacity: capacity }))] } });
  };
  const toggleLock = (activityId: string, accessSeq: number) => {
    const exists = current.change.locked_placements.some((item) => item.activity_id === activityId && item.access_seq === accessSeq);
    const locks = exists ? current.change.locked_placements.filter((item) => item.activity_id !== activityId || item.access_seq !== accessSeq) : [...current.change.locked_placements, { activity_id: activityId, access_seq: accessSeq }];
    setCurrent({ ...current, change: { ...current.change, locked_placements: locks } });
  };
  const save = async () => {
    try {
      const updated = await onUpdate({ supply_overrides: current.change.supply_overrides, locked_placements: current.change.locked_placements, rationale: current.change.rationale });
      setCurrent(updated);
      setNotice("Review saved and checked again.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not save the recovery review.");
    }
  };

  return <section className="space-y-4 rounded-2xl border border-red-300/25 bg-slate-950/45 p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-red-300">Review change</p><h3 className="mt-1 text-lg font-bold text-white">Controller recovery draft</h3><p className="mt-1 text-xs text-slate-400">Source: {current.source.replaceAll("_", " ")} · Base {current.change.base_schedule_id.slice(0, 8)}</p></div><span className={`rounded-full border px-3 py-1 text-xs font-bold ${current.status === "ready" ? "border-emerald-300/35 bg-emerald-300/10 text-emerald-100" : "border-amber-300/35 bg-amber-300/10 text-amber-100"}`}>{current.status === "ready" ? "Ready to confirm" : "Needs review"}</span></div>
    <div className="grid gap-2 sm:grid-cols-3"><Stat label="Supply changes" value={String(groups.length)} detail="locations affected" /><Stat label="Locked work" value={String(current.change.locked_placements.length)} detail="placements held fixed" /><Stat label="Result" value={run.demo ? "Demo replay" : recoveryAvailable ? "C recovery" : "Unavailable"} detail="no direct schedule edits" /></div>
    <div className="space-y-2 rounded-xl border border-slate-700 bg-slate-900/50 p-3"><p className="text-sm font-bold text-white">Capacity scope</p>{groups.map(([locationId, group]) => <div key={locationId} className="grid gap-2 rounded-lg border border-slate-700 bg-slate-950/65 p-3 md:grid-cols-[1fr_6rem_13rem]"><div><p className="text-xs font-semibold text-white">{readableLocation(locationId)}</p><p className="mt-1 font-mono text-[10px] text-slate-500">{locationId}</p></div><label className="text-xs text-slate-300">Capacity<input type="number" min="0" value={group.capacity} onChange={(event) => updateGroup(locationId, Number(event.target.value), group.weeks)} className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-2 py-1.5 text-white" /></label><label className="text-xs text-slate-300">Weeks<input value={group.weeks.join(", ")} onChange={(event) => { const weeks = parseWeeks(event.target.value); if (weeks) updateGroup(locationId, group.capacity, weeks); }} className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-2 py-1.5 text-white" /></label></div>)}</div>
    <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-bold text-white">Keep approved work fixed</p><span className="text-xs text-slate-400">{current.change.locked_placements.length} selected</span></div><input value={placementFilter} onChange={(event) => setPlacementFilter(event.target.value)} placeholder="Search activity ID or access number" className="mt-3 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-500" /><div className="mt-2 max-h-44 overflow-y-auto rounded-lg border border-slate-700 bg-slate-950/65 p-1">{placements.map((item) => { const locked = current.change.locked_placements.some((lock) => lock.activity_id === item.activity_id && lock.access_seq === item.access_seq); return <label key={`${item.activity_id}-${item.access_seq}`} className="flex cursor-pointer items-center justify-between rounded-lg px-2 py-2 text-xs hover:bg-slate-800"><span><b>{item.activity_id}</b><span className="text-slate-500"> · access {item.access_seq} · week {item.week}</span></span><input type="checkbox" checked={locked} onChange={() => toggleLock(item.activity_id, item.access_seq)} className="h-4 w-4 accent-red-500" /></label>; })}</div></div>
    <label className="block text-xs font-semibold text-slate-300">Controller note<textarea value={current.change.rationale ?? ""} onChange={(event) => setCurrent({ ...current, change: { ...current.change, rationale: event.target.value } })} maxLength={500} className="mt-1 min-h-20 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm font-normal text-white" placeholder="Why is this change needed?" /></label>
    {issues.length > 0 && <div className="rounded-xl border border-amber-300/35 bg-amber-300/10 p-3 text-xs text-amber-100"><p className="font-bold">Resolve before confirmation</p><ul className="mt-1 list-disc pl-4">{issues.map((item) => <li key={item}>{item}</li>)}</ul></div>}
    {notice && <p role="alert" className="rounded-xl border border-red-300/30 bg-red-500/10 p-3 text-xs text-red-100">{notice}</p>}
    <div className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => void save()} className="rounded-xl border border-red-300/40 bg-red-500/10 px-4 py-2 text-xs font-bold text-red-100 disabled:cursor-not-allowed disabled:text-slate-500">Save review</button>{run.demo ? <button disabled={busy || current.status !== "ready"} onClick={() => void onReplay(current.draft_id)} className="rounded-xl bg-red-500 px-4 py-2 text-xs font-bold text-white disabled:bg-slate-700">Replay fixed public example</button> : <button disabled={busy || current.status !== "ready" || !recoveryAvailable} onClick={() => void onConfirm(current.draft_id)} className="rounded-xl bg-red-500 px-4 py-2 text-xs font-bold text-white disabled:bg-slate-700">Confirm and re-optimise</button>}</div>
  </section>;
}

export function RecoverySandbox({ run, capabilities, busy, onOpenDemo, onReplay, onCreateDraft, onCreateSupplyDraft, onUpdateDraft, onConfirmDraft }: {
  run: RunView | null;
  capabilities: CapabilityReport | null;
  busy: boolean;
  onOpenDemo: () => Promise<void>;
  onReplay: (draftId?: string) => Promise<void>;
  onCreateDraft: (text: string) => Promise<ScenarioChangeDraft>;
  onCreateSupplyDraft: (file: File) => Promise<ScenarioChangeDraft>;
  onUpdateDraft: (draftId: string, payload: ScenarioChangeDraftUpdate) => Promise<ScenarioChangeDraft>;
  onConfirmDraft: (draftId: string) => Promise<void>;
}) {
  const [request, setRequest] = useState("");
  const [supplyFile, setSupplyFile] = useState<File | null>(null);
  const [draft, setDraft] = useState<ScenarioChangeDraft | null>(null);
  const [notice, setNotice] = useState("");
  const isDemo = run?.demo === true;
  const recoveryAvailable = Boolean(!isDemo && run && capabilities?.recovery.available && capabilities.recovery.supported_scenarios.includes(run.scenario));
  const naturalLanguageAvailable = Boolean(run && capabilities?.disruption_drafts.available && (isDemo || recoveryAvailable));
  const createCsvDraft = async () => { if (!supplyFile) return; try { setDraft(await onCreateSupplyDraft(supplyFile)); setNotice(""); } catch (error) { setNotice(error instanceof Error ? error.message : "Could not review this supply CSV."); } };
  const parse = async () => { if (!request.trim()) return; try { setDraft(await onCreateDraft(request.trim())); setNotice(""); } catch (error) { setNotice(error instanceof Error ? error.message : "The disruption draft parser is unavailable."); } };

  return <section className="editorial-card c151-card mt-5 rounded-2xl border border-red-400/25 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
    <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">Recovery sandbox</p><h2 className="section-heading mt-1 text-xl font-bold text-white">Stage a disruption review</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Compare a supply change, keep approved access fixed, and ask the Scenario C recovery model for a locally checked alternative.</p>
    {!run ? <div className="mt-4 rounded-xl border border-slate-700 bg-slate-900/60 p-4 text-sm text-slate-300"><p>Start with a completed run, or explore the workflow with the public fixture.</p><button disabled={!capabilities?.public_demo_recovery.available || busy} onClick={() => void onOpenDemo()} className="mt-3 rounded-xl border border-red-300/40 bg-red-500/10 px-4 py-2.5 font-bold text-red-100 disabled:cursor-not-allowed disabled:text-slate-500">Open public recovery demo</button></div> : <div className="mt-5 space-y-4">
      {isDemo && <div className="rounded-xl border border-amber-300/35 bg-amber-300/10 p-3 text-xs text-amber-50"><b>Public demonstration fixture.</b> {run.demo_notice ?? "This is not a newly optimised schedule."}</div>}
      <div className="grid gap-3 lg:grid-cols-2"><div className="rounded-2xl border border-slate-700 bg-slate-900/60 p-4"><p className="text-xs font-bold uppercase tracking-[0.16em] text-red-300">Option A</p><p className="mt-1 font-bold text-white">Upload revised supply</p><p className="mt-1 text-xs leading-5 text-slate-400">Use an edited official <code>04_LOCATION_SUPPLY.csv</code>. Only capacity changes are accepted.</p><input type="file" accept=".csv,text/csv" onChange={(event) => setSupplyFile(event.target.files?.[0] ?? null)} className="mt-4 block w-full text-xs text-slate-300" /><button disabled={!supplyFile || busy} onClick={() => void createCsvDraft()} className="mt-3 rounded-xl border border-red-300/40 bg-red-500/10 px-4 py-2.5 text-xs font-bold text-red-100 disabled:cursor-not-allowed disabled:text-slate-500">Review CSV changes</button></div>{naturalLanguageAvailable ? <div className="rounded-2xl border border-slate-700 bg-slate-900/60 p-4"><p className="text-xs font-bold uppercase tracking-[0.16em] text-red-300">Option B{isDemo ? " · public demo" : " · Scenario C"}</p><p className="mt-1 font-bold text-white">Describe the disruption</p><p className="mt-1 text-xs leading-5 text-slate-400">Gemini receives this text plus bounded valid location, week, and placement identifiers only. It never receives CSV content, a full schedule, exports, or organiser material.</p><textarea value={request} onChange={(event) => setRequest(event.target.value)} maxLength={1000} className="mt-3 min-h-24 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-500" placeholder="For example: reduce capacity at ALP S01 to S02 in week 22 and lock A001 access 1." /><button disabled={busy || !request.trim()} onClick={() => void parse()} className="mt-3 rounded-xl bg-red-500 px-4 py-2.5 text-xs font-bold text-white disabled:cursor-not-allowed disabled:bg-slate-700">Create AI review draft</button></div> : <div className="rounded-2xl border border-slate-700 bg-slate-900/40 p-4"><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Natural language</p><p className="mt-1 font-bold text-slate-300">Available for Scenario C recovery only</p><p className="mt-2 text-xs leading-5 text-slate-500">Run a successful live Scenario C schedule first. Scenario A/B and unfinished runs use CSV plus manual review only.</p></div>}</div>
      {draft && <ReviewDraft draft={draft} run={run} busy={busy} recoveryAvailable={recoveryAvailable} onUpdate={(payload) => onUpdateDraft(draft.draft_id, payload)} onConfirm={onConfirmDraft} onReplay={onReplay} />}{!isDemo && !recoveryAvailable && <p className="text-xs text-amber-100">{capabilities?.recovery.message ?? "Checking recovery capability."} Recovery is currently supported only for Scenario C.</p>}{notice && <p role="alert" className="rounded-xl border border-amber-300/35 bg-amber-300/10 p-3 text-xs text-amber-100">{notice}</p>}
    </div>}
  </section>;
}
