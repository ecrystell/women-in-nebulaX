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
  return `${kindName} - ${lineNames[line] ?? line} - ${placeName} - ${boundName}`;
}

function compactWeeks(weeks: number[]) {
  const values = [...new Set(weeks)].sort((left, right) => left - right);
  const ranges: string[] = [];
  for (let index = 0; index < values.length; index += 1) {
    let end = index;
    while (values[end + 1] === values[end] + 1) end += 1;
    ranges.push(end === index ? String(values[index]) : `${values[index]}-${values[end]}`);
    index = end;
  }
  return ranges.join(", ");
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

function ReviewDraft({ draft, run, busy, recoveryAvailable, onUpdate, onConfirm, onReplay }: DraftProps) {
  const [current, setCurrent] = useState(draft);
  const [placementFilter, setPlacementFilter] = useState("");
  const [notice, setNotice] = useState("");
  const [weekInputs, setWeekInputs] = useState<Record<string, string>>({});
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
      setNotice("Review saved. The draft was checked again.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not save this recovery review."); }
  };
  const visiblePlacements = (run.schedule?.placements ?? []).filter((item) => `${item.activity_id} ${item.access_seq}`.toLowerCase().includes(placementFilter.toLowerCase())).slice(0, 20);
  const issueList = [...current.unresolved_references, ...current.field_errors.map((item) => `${item.field}: ${item.message}`)];

  return <div className="mt-5 space-y-4 border-t border-red-400/20 pt-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-[0.18em] text-red-300">Step 2 - Review the change</p><h3 className="mt-1 text-lg font-bold text-white">Recovery review</h3><p className="mt-1 text-xs text-slate-400">From {current.source.replaceAll("_", " ")} - base schedule {current.change.base_schedule_id.slice(0, 8)}</p></div><span className={`rounded-full border px-3 py-1 text-xs font-bold ${current.status === "ready" ? "border-emerald-300/35 bg-emerald-300/10 text-emerald-100" : "border-amber-300/35 bg-amber-300/10 text-amber-100"}`}>{current.status === "ready" ? "Ready to review" : "Needs attention"}</span></div>
    <div className="grid gap-2 sm:grid-cols-3"><Stat label="Supply changes" value={String(groups.length)} detail="locations affected" /><Stat label="Locked work" value={String(current.change.locked_placements.length)} detail="placements kept fixed" /><Stat label="Result" value={run.demo ? "Demo replay only" : recoveryAvailable ? "Ready to optimise" : "Solver unavailable"} detail="No schedule is changed yet" small /></div>
    <div className="rounded-2xl border border-slate-700 bg-slate-950/45 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-bold text-white">1. Capacity changes</p><p className="mt-1 text-xs text-slate-400">Edit capacity or planning weeks. Use commas and ranges, for example <span className="font-mono text-slate-300">4-6, 9</span>.</p></div><span className="text-xs text-slate-500">Official supply locations only</span></div><div className="mt-3 space-y-2">{groups.map(([locationId, group]) => <div key={locationId} className="grid gap-3 rounded-xl border border-slate-700 bg-slate-900/60 p-3 md:grid-cols-[minmax(0,1fr)_7rem_minmax(12rem,0.8fr)] md:items-end"><div><p className="text-sm font-semibold text-white">{readableLocation(locationId)}</p><p className="mt-1 font-mono text-[11px] text-slate-500">{locationId}</p></div><label className="text-xs font-semibold text-slate-300">Capacity<input aria-label={`${locationId} capacity`} type="number" min="0" value={group.capacity} onChange={(event) => updateGroup(locationId, Number(event.target.value), group.weeks)} className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none transition focus:border-red-300" /></label><label className="text-xs font-semibold text-slate-300">Weeks<input aria-label={`${locationId} weeks`} value={weekInputs[locationId] ?? compactWeeks(group.weeks)} onChange={(event) => setWeekInputs({ ...weekInputs, [locationId]: event.target.value })} onBlur={(event) => { const weeks = parseWeeks(event.target.value); if (!weeks?.length) { setNotice("Use week numbers and ranges, such as 4-6, 9."); return; } updateGroup(locationId, group.capacity, weeks); setWeekInputs({ ...weekInputs, [locationId]: compactWeeks(weeks) }); }} className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none transition focus:border-red-300" /></label></div>)}</div></div>
    <div className="rounded-2xl border border-slate-700 bg-slate-950/45 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="font-bold text-white">2. Keep approved work fixed</p><p className="mt-1 text-xs text-slate-400">Select exact access placements that must not move during recovery.</p></div><span className="rounded-full bg-red-400/10 px-3 py-1 text-xs font-bold text-red-100">{current.change.locked_placements.length} selected</span></div><input value={placementFilter} onChange={(event) => setPlacementFilter(event.target.value)} placeholder="Search activity ID or access number" className="mt-3 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-red-300" /><div className="mt-2 max-h-48 overflow-y-auto rounded-xl border border-slate-700 bg-slate-950/60 p-2">{visiblePlacements.map((item) => { const locked = current.change.locked_placements.some((lock) => lock.activity_id === item.activity_id && lock.access_seq === item.access_seq); return <label key={`${item.activity_id}-${item.access_seq}`} className="flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-xs transition hover:bg-slate-800"><span className="text-slate-200"><b>{item.activity_id}</b><span className="text-slate-500"> - access {item.access_seq} - week {item.week}</span></span><input type="checkbox" checked={locked} onChange={() => toggleLock(item.activity_id, item.access_seq)} className="h-4 w-4 accent-red-500" /></label>; })}{visiblePlacements.length === 0 && <p className="p-3 text-xs text-slate-500">No matching baseline placement.</p>}</div></div>
    <label className="block rounded-2xl border border-slate-700 bg-slate-950/45 p-4 text-xs font-semibold text-slate-300">3. Controller note<textarea value={current.change.rationale ?? ""} onChange={(event) => setCurrent({ ...current, change: { ...current.change, rationale: event.target.value } })} maxLength={500} placeholder="Why is this change needed?" className="mt-2 min-h-20 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm font-normal text-white outline-none transition placeholder:text-slate-500 focus:border-red-300" /></label>
    {issueList.length > 0 && <div className="rounded-xl border border-amber-300/35 bg-amber-300/10 p-3 text-xs text-amber-100"><p className="font-bold">Resolve before continuing</p><ul className="mt-1 list-disc space-y-1 pl-4">{issueList.map((item) => <li key={item}>{item}</li>)}</ul></div>}{notice && <p role="alert" className="rounded-xl border border-red-300/30 bg-red-500/10 p-3 text-xs text-red-100">{notice}</p>}
    <div className="flex flex-wrap items-center gap-2"><button disabled={busy} onClick={() => void save()} className="rounded-xl border border-red-300/40 bg-red-500/10 px-4 py-2.5 text-xs font-bold text-red-100 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:border-slate-700 disabled:text-slate-500">Save review</button>{run.demo ? <button disabled={busy || current.status !== "ready"} onClick={() => void onReplay(current.draft_id)} className="rounded-xl bg-red-500 px-4 py-2.5 text-xs font-bold text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:bg-slate-700">Replay fixed public example</button> : <button disabled={busy || current.status !== "ready" || !recoveryAvailable} onClick={() => void onConfirm(current.draft_id)} className="rounded-xl bg-red-500 px-4 py-2.5 text-xs font-bold text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:bg-slate-700">Confirm and re-optimise</button>}</div>
    {run.demo && <p className="text-xs text-amber-100">This is a public demonstration replay, not a newly optimised schedule.</p>}{!run.demo && !recoveryAvailable && <p className="text-xs text-amber-100">Your reviewed draft remains in memory, but a revised schedule cannot be created until the recovery solver is connected.</p>}
  </div>;
}

function Stat({ label, value, detail, small = false }: { label: string; value: string; detail: string; small?: boolean }) { return <div className="rounded-xl border border-slate-700 bg-slate-950/55 p-3"><p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">{label}</p><p className={`mt-1 font-bold text-white ${small ? "text-sm" : "text-2xl"}`}>{value}</p><p className="text-xs text-slate-400">{detail}</p></div>; }

export function RecoverySandbox({ run, capabilities, busy, onOpenDemo, onReplay, onCreateDraft, onCreateSupplyDraft, onUpdateDraft, onConfirmDraft }: {
  run: RunView | null; capabilities: CapabilityReport | null; busy: boolean; onOpenDemo: () => Promise<void>; onReplay: (draftId?: string) => Promise<void>; onCreateDraft: (text: string) => Promise<ScenarioChangeDraft>; onCreateSupplyDraft: (file: File) => Promise<ScenarioChangeDraft>; onUpdateDraft: (draftId: string, payload: ScenarioChangeDraftUpdate) => Promise<ScenarioChangeDraft>; onConfirmDraft: (draftId: string) => Promise<void>;
}) {
  const [request, setRequest] = useState(""); const [supplyFile, setSupplyFile] = useState<File | null>(null); const [draft, setDraft] = useState<ScenarioChangeDraft | null>(null); const [notice, setNotice] = useState(""); const isDemo = run?.demo === true;
  const recoveryAvailable = Boolean(!isDemo && run && capabilities?.recovery.available && capabilities.recovery.supported_scenarios.includes(run.scenario));
  const createCsvDraft = async () => { if (!supplyFile) return; try { setDraft(await onCreateSupplyDraft(supplyFile)); setNotice(""); } catch (error) { setNotice(error instanceof Error ? error.message : "Could not review this supply CSV."); } };
  const parse = async () => { if (!request.trim()) return; try { setDraft(await onCreateDraft(request.trim())); setNotice(""); } catch (error) { setNotice(error instanceof Error ? error.message : "The public demo parser is unavailable."); } };
  return <section className="editorial-card c151-card mt-5 rounded-2xl border border-red-400/25 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur"><p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">Recovery sandbox</p><h2 className="section-heading mt-1 text-xl font-bold text-white">Stage a disruption review</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Describe a supply disruption, check the proposed scope, then choose the work that should stay fixed. Scenario C reviews can create a real locally checked recovery run after confirmation.</p>{!run ? <div className="mt-4 rounded-xl border border-slate-700 bg-slate-900/60 p-4 text-sm text-slate-300"><p>Start with a completed run, or explore the controller workflow with the public fixture.</p><button disabled={!capabilities?.public_demo_recovery.available || busy} onClick={() => void onOpenDemo()} className="mt-3 rounded-xl border border-red-300/40 bg-red-500/10 px-4 py-2.5 font-bold text-red-100 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:border-slate-700 disabled:text-slate-500">Open public recovery demo</button></div> : <div className="mt-5 space-y-4">{isDemo && <div className="rounded-xl border border-amber-300/35 bg-amber-300/10 p-3 text-xs text-amber-50"><b>Public demonstration fixture.</b> {run.demo_notice ?? "This is not a newly optimised schedule."}</div>}<div className="grid gap-3 lg:grid-cols-2"><div className="rounded-2xl border border-slate-700 bg-slate-900/60 p-4"><p className="text-xs font-bold uppercase tracking-[0.16em] text-red-300">Option A</p><p className="mt-1 font-bold text-white">Upload revised supply</p><p className="mt-1 text-xs leading-5 text-slate-400">Use an edited official <code>04_LOCATION_SUPPLY.csv</code>. Only capacity changes are accepted and start out applying to every planning week.</p><input type="file" accept=".csv,text/csv" onChange={(event) => setSupplyFile(event.target.files?.[0] ?? null)} className="mt-4 block w-full text-xs text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:font-semibold file:text-slate-100" /><button disabled={!supplyFile || busy} onClick={() => void createCsvDraft()} className="mt-3 rounded-xl border border-red-300/40 bg-red-500/10 px-4 py-2.5 text-xs font-bold text-red-100 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:border-slate-700 disabled:text-slate-500">Review CSV changes</button></div>{isDemo ? <div className="rounded-2xl border border-slate-700 bg-slate-900/60 p-4"><p className="text-xs font-bold uppercase tracking-[0.16em] text-red-300">Option B - public demo</p><p className="mt-1 font-bold text-white">Describe the disruption</p><p className="mt-1 text-xs leading-5 text-slate-400">Gemini can interpret only this public fixture's bounded identifiers. It cannot change a schedule or judge feasibility.</p><textarea value={request} onChange={(event) => setRequest(event.target.value)} maxLength={1000} className="mt-3 min-h-24 w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-red-300" placeholder="For example: reduce capacity at ALP S01 to S02 in week 22 and lock A001 access 1." /><button disabled={!capabilities?.disruption_drafts.available || busy || !request.trim()} onClick={() => void parse()} className="mt-3 rounded-xl bg-red-500 px-4 py-2.5 text-xs font-bold text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:bg-slate-700">Create AI review draft</button></div> : <div className="rounded-2xl border border-slate-700 bg-slate-900/40 p-4"><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Natural language</p><p className="mt-1 font-bold text-slate-300">Unavailable for uploaded data</p><p className="mt-2 text-xs leading-5 text-slate-500">For privacy, hidden uploaded data is never sent to Gemini. Upload a supply CSV and use the manual review controls instead.</p></div>}</div>{draft && <ReviewDraft draft={draft} run={run} busy={busy} recoveryAvailable={recoveryAvailable} onUpdate={(payload) => onUpdateDraft(draft.draft_id, payload)} onConfirm={(draftId) => onConfirmDraft(draftId)} onReplay={(draftId) => onReplay(draftId)} />}{!isDemo && !recoveryAvailable && <p className="text-xs text-amber-100">{capabilities?.recovery.message ?? "Checking recovery capability."} Recovery is currently supported only for Scenario C.</p>}{notice && <p role="alert" className="rounded-xl border border-amber-300/35 bg-amber-300/10 p-3 text-xs text-amber-100">{notice}</p>}</div>}</section>;
}
