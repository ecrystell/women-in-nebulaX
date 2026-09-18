import { useEffect, useState } from "react";
import { railAccessApi, RailAccessApiError } from "./api/client";
import type { Health, OrganiserEvidenceInput, OrganiserReportedOutcome, RunView, Scenario } from "./api/types";
import { TrainScene } from "./TrainScene";

type MaintenanceEvent = {
  id: string;
  day: number;
  month: number;
  year: number;
  title: string;
  station: string;
  line: string;
  time: string;
  people: string;
  colour: string;
};

const months = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

const maintenanceEvents: MaintenanceEvent[] = [
  {
    id: "s03",
    day: 8,
    month: 8,
    year: 2026,
    title: "Signalling inspection",
    station: "S03",
    line: "ALP",
    time: "00:45–04:30",
    people: "12 engineering staff",
    colour: "bg-cyan-400"
  },
  {
    id: "h01",
    day: 16,
    month: 8,
    year: 2026,
    title: "Rail grinding",
    station: "H01",
    line: "ALP/BET",
    time: "01:00–04:45",
    people: "18 track workers",
    colour: "bg-amber-400"
  },
  {
    id: "s17",
    day: 23,
    month: 8,
    year: 2026,
    title: "Platform screen-door servicing",
    station: "S17",
    line: "BET",
    time: "00:30–03:50",
    people: "8 maintenance staff",
    colour: "bg-rose-400"
  }
];

const stars = [
  ["5%", "12%", 2, "0s"], ["12%", "42%", 3, "1.4s"], ["18%", "19%", 2, "2.1s"],
  ["24%", "70%", 3, "0.6s"], ["31%", "9%", 2, "2.8s"], ["38%", "55%", 2, "1.1s"],
  ["44%", "31%", 3, "2.4s"], ["51%", "15%", 2, "0.3s"], ["57%", "76%", 3, "1.8s"],
  ["63%", "43%", 2, "2.6s"], ["69%", "7%", 3, "0.9s"], ["75%", "63%", 2, "1.5s"],
  ["82%", "26%", 3, "2.9s"], ["89%", "48%", 2, "0.5s"], ["94%", "17%", 3, "2s"]
] as const;

function TrackDiagram({ activeStation }: { activeStation: string | null }) {
  const alphaStations = ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"];
  const betaStations = ["S11", "S12", "S13", "S14", "S15", "S16", "S17", "S18"];
  const stationPositions = [350, 420, 490, 560, 730, 800, 870, 920];
  const interchangeStations = ["H01", "H02"];
  const alphaActive = activeStation !== null && (alphaStations.includes(activeStation) || interchangeStations.includes(activeStation));
  const betaActive = activeStation !== null && (betaStations.includes(activeStation) || interchangeStations.includes(activeStation));

  const stationNode = (name: string, x: number, y: number, colour: string) => {
    const active = name === activeStation;
    return (
      <g key={name}>
        {active && <circle cx={x} cy={y} r="26" fill={colour} opacity="0.42" />}
        <circle cx={x} cy={y} r={active ? "13" : "8"} fill={active ? colour : "#111827"} stroke={active ? "#f8fafc" : colour} strokeWidth={active ? "4" : "3"} />
        <text x={x} y={y - 26} textAnchor="middle" fill={active ? "#ffffff" : "#e2e8f0"} fontSize="15" fontWeight="700">{name}</text>
      </g>
    );
  };

  const interchangeNode = (name: string, x: number, y: number, labelBelow = false) => {
    const active = name === activeStation;
    const labelY = labelBelow ? y + 43 : y - 34;
    return (
      <g key={`${name}-${y}`}>
        {active && <rect x={x - 24} y={y - 35} width="48" height="70" rx="24" fill="#fbbf24" opacity="0.35" />}
        <rect x={x - 14} y={y - 25} width="28" height="50" rx="14" fill={active ? "#fbbf24" : "#f8fafc"} stroke="#111827" strokeWidth={active ? "5" : "4"} />
        <text x={x} y={labelY} textAnchor="middle" fill={active ? "#fff7cc" : "#fef3c7"} fontSize="13" fontWeight="800">{name}</text>
      </g>
    );
  };

  return (
    <section className="editorial-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">01 · Network view</p>
          <h2 className="mt-1 text-xl font-bold text-white">Dual-line track access topology</h2>
        </div>
        <div className="space-y-1 text-right text-xs text-slate-300">
          <p><span className="mr-1 inline-block h-2 w-2 rounded-full bg-rose-400" />ALP · Red line</p>
          <p><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-400" />BET · Green line</p>
        </div>
      </div>

      <svg className="mt-4 h-auto w-full" viewBox="0 0 1000 330" role="img" aria-label="Metro Line Alpha and Metro Line Beta station topology">

        {["H01", "H02"].map((station, index) => {
          const x = index === 0 ? 610 : 670;
          const active = activeStation === station;
          return (
            <g key={station}>
              {active && <line x1={x} y1="143" x2={x} y2="235" stroke="#fbbf24" strokeWidth="17" strokeLinecap="round" opacity="0.28" />}
              <line x1={x} y1="143" x2={x} y2="235" stroke={active ? "#fbbf24" : "#f8fafc"} strokeWidth={active ? "7" : "5"} strokeLinecap="round" opacity="0.9" />
            </g>
          );
        })}

        <rect x="10" y="96" width="60" height="28" rx="6" fill="#df5750" />
        <text x="40" y="115" textAnchor="middle" fill="#ffffff" fontSize="14" fontWeight="800">ALP</text>
        <text x="82" y="115" fill="#f8b4b1" fontSize="14" fontWeight="700">Metro Line Alpha · Red line</text>
        {alphaActive && <line x1="330" y1="118" x2="940" y2="118" stroke="#fb7185" strokeWidth="16" strokeLinecap="round" opacity="0.22" />}
        <line x1="330" y1="118" x2="940" y2="118" stroke={alphaActive ? "#fb7185" : "#e45850"} strokeWidth={alphaActive ? "7" : "5"} strokeLinecap="round" opacity={alphaActive ? "1" : "0.8"} />
        {alphaStations.map((station, index) => stationNode(station, stationPositions[index], 118, "#e45850"))}
        {["H01", "H02"].map((station, index) => interchangeNode(station, index === 0 ? 610 : 670, 118))}

        <rect x="10" y="238" width="60" height="28" rx="6" fill="#5fc486" />
        <text x="40" y="257" textAnchor="middle" fill="#ffffff" fontSize="14" fontWeight="800">BET</text>
        <text x="82" y="257" fill="#b7efca" fontSize="14" fontWeight="700">Metro Line Beta · Green line</text>
        {betaActive && <line x1="330" y1="260" x2="940" y2="260" stroke="#6ee7a0" strokeWidth="16" strokeLinecap="round" opacity="0.22" />}
        <line x1="330" y1="260" x2="940" y2="260" stroke={betaActive ? "#6ee7a0" : "#63c38a"} strokeWidth={betaActive ? "7" : "5"} strokeLinecap="round" opacity={betaActive ? "1" : "0.8"} />
        {betaStations.map((station, index) => stationNode(station, stationPositions[index], 260, "#63c38a"))}
        {["H01", "H02"].map((station, index) => interchangeNode(station, index === 0 ? 610 : 670, 260, true))}
      </svg>
      <p className="mt-2 text-xs leading-5 text-slate-400">
        Hover a maintenance date to fill and brighten its station. H01 and H02 are interchanges between both lines.
      </p>
    </section>
  );
}

function Calendar({
  month,
  year,
  activeEvent,
  onMonthChange,
  onYearChange,
  onEventHover
}: {
  month: number;
  year: number;
  activeEvent: MaintenanceEvent | null;
  onMonthChange: (direction: number) => void;
  onYearChange: (direction: number) => void;
  onEventHover: (event: MaintenanceEvent | null) => void;
}) {
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstWeekday = new Date(year, month, 1).getDay();
  const cells = Array.from({ length: firstWeekday + daysInMonth }, (_, index) => index - firstWeekday + 1);

  const eventForDay = (day: number) => maintenanceEvents.find(
    (event) => event.day === day && event.month === month && event.year === year
  );

  return (
    <section className="editorial-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">02 · Maintenance calendar</p>
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button className="calendar-arrow" onClick={() => onMonthChange(-1)} aria-label="Previous month">←</button>
          <span className="min-w-28 text-center font-bold text-white">{months[month]}</span>
          <button className="calendar-arrow" onClick={() => onMonthChange(1)} aria-label="Next month">→</button>
        </div>
        <div className="flex items-center gap-2">
          <button className="calendar-arrow" onClick={() => onYearChange(-1)} aria-label="Previous year">←</button>
          <span className="min-w-12 text-center font-bold text-white">{year}</span>
          <button className="calendar-arrow" onClick={() => onYearChange(1)} aria-label="Next year">→</button>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-7 gap-1 text-center text-xs">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
          <span key={day} className="pb-1 text-slate-500">{day}</span>
        ))}
        {cells.map((day, index) => {
          if (day < 1) return <span key={index} />;
          const event = eventForDay(day);
          return (
            event ? (
              <button
                key={day}
                aria-label={`${day} ${months[month]}: ${event.title}`}
                className="calendar-day calendar-event-date"
                onMouseEnter={() => onEventHover(event)}
                onFocus={() => onEventHover(event)}
                onMouseLeave={() => onEventHover(null)}
                onBlur={() => onEventHover(null)}
              >
                <span className="font-bold">{day}</span>
                <span className={`calendar-event ${event.colour}`} aria-hidden="true" />
              </button>
            ) : (
              <div key={day} className="calendar-day"><span>{day}</span></div>
            )
          );
        })}
      </div>

      <div className="mt-5 rounded-xl border border-slate-700 bg-slate-900/80 p-3">
        {activeEvent ? (
          <div>
            <p className="font-semibold text-white">{activeEvent.title}</p>
            <p className="mt-1 text-sm text-cyan-200">{activeEvent.station} · {activeEvent.line} · {activeEvent.time}</p>
            <p className="mt-1 text-xs text-slate-400">{activeEvent.people}</p>
          </div>
        ) : (
          <p className="text-sm text-slate-400">Hover a scheduled maintenance date for location, time and crew details.</p>
        )}
      </div>
    </section>
  );
}

function UploadDropzone({
  id,
  title,
  description,
  files,
  multiple,
  onFiles
}: {
  id: string;
  title: string;
  description: string;
  files: File[];
  multiple: boolean;
  onFiles: (files: File[]) => void;
}) {
  const [dragging, setDragging] = useState(false);

  const receiveFiles = (incoming: File[]) => {
    const csvFiles = incoming.filter((file) => file.name.toLowerCase().endsWith(".csv"));
    onFiles(multiple ? csvFiles : csvFiles.slice(0, 1));
  };

  return (
    <label
      htmlFor={id}
      className={`block cursor-pointer rounded-xl border border-dashed p-4 transition ${dragging ? "border-cyan-300 bg-cyan-300/10" : "border-slate-600 bg-slate-900/60 hover:border-cyan-400/70"}`}
      onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        receiveFiles(Array.from(event.dataTransfer.files));
      }}
    >
      <input
        id={id}
        className="sr-only"
        type="file"
        accept=".csv,text/csv"
        multiple={multiple}
        onChange={(event) => receiveFiles(Array.from(event.target.files ?? []))}
      />
      <div className="flex gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-400/15 text-xl text-cyan-200">↓</span>
        <div>
          <p className="font-semibold text-white">{title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-400">{description}</p>
          <p className="mt-2 text-xs font-semibold text-cyan-200">
            {files.length ? `${files.length} CSV file${files.length === 1 ? "" : "s"} selected` : "Drop CSV files here or browse"}
          </p>
        </div>
      </div>
    </label>
  );
}

function SubmissionEvidencePanel({
  run,
  busy,
  notice,
  onCreatePackage,
  onRecordEvidence
}: {
  run: RunView | null;
  busy: boolean;
  notice: string;
  onCreatePackage: () => Promise<void>;
  onRecordEvidence: (packageId: string, payload: OrganiserEvidenceInput) => Promise<void>;
}) {
  const [attemptNumber, setAttemptNumber] = useState(1);
  const [submittedAt, setSubmittedAt] = useState(() => new Date().toISOString().slice(0, 16));
  const [outcome, setOutcome] = useState<OrganiserReportedOutcome>("unknown");
  const [reference, setReference] = useState("");
  const [digest, setDigest] = useState("");
  const [note, setNote] = useState("");
  const localClean = run?.status === "succeeded" && run.validation_report?.hard_violations.length === 0;
  const latestPackage = run?.submission_packages.at(-1);

  if (!run) return null;

  return (
    <section className="mt-5 rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">07 · Organiser evidence</p>
      <h2 className="mt-1 text-xl font-bold text-white">Manual submission package</h2>
      <p className="mt-2 text-sm leading-6 text-slate-400">
        Run {run.run_id.slice(0, 8)} · {run.status}. Local result: {run.validation_report?.status ?? "unavailable"}.
      </p>
      {run.validation_report && (
        <p className="mt-2 text-xs leading-5 text-amber-100">
          {run.validation_report.message} Organiser feedback recorded here remains unverified until a supported organiser report integration exists.
        </p>
      )}
      {run.problem && <p className="mt-2 text-sm text-rose-200">{run.problem.message}</p>}
      {notice && <p className="mt-3 text-sm text-cyan-100">{notice}</p>}

      {!localClean ? (
        <p className="mt-4 rounded-xl border border-slate-700 bg-slate-900/70 p-3 text-sm text-slate-400">
          Submission packages are available only after a locally clean succeeded run. Blocked Scenario B/C runs and failed candidates cannot be downloaded for submission.
        </p>
      ) : (
        <div className="mt-4 space-y-4">
          <button
            disabled={busy}
            onClick={() => void onCreatePackage()}
            className="rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            Create manual upload ZIP
          </button>

          {run.submission_packages.map((submissionPackage) => (
            <div key={submissionPackage.package_id} className="rounded-xl border border-slate-700 bg-slate-900/70 p-3 text-sm">
              <p className="font-semibold text-white">Package {submissionPackage.package_id.slice(0, 8)} · commit {submissionPackage.build_commit.slice(0, 12)}</p>
              <div className="mt-2 flex flex-wrap gap-3 text-cyan-200">
                <a href={railAccessApi.getSubmissionPackageUrl(run.run_id, submissionPackage.package_id)} className="font-semibold underline">Download ZIP</a>
                {submissionPackage.organiser_evidence && (
                  <a href={railAccessApi.getEvidenceRecordUrl(run.run_id, submissionPackage.package_id)} className="font-semibold underline">Download evidence JSON</a>
                )}
              </div>
              {submissionPackage.organiser_evidence && (
                <p className="mt-2 text-xs text-slate-300">Attempt {submissionPackage.organiser_evidence.attempt_number}: {submissionPackage.organiser_evidence.reported_outcome} (locally unverified).</p>
              )}
            </div>
          ))}

          {latestPackage && !latestPackage.organiser_evidence && (
            <form
              className="rounded-xl border border-amber-400/30 bg-amber-400/5 p-4"
              onSubmit={(event) => {
                event.preventDefault();
                const submitted = new Date(submittedAt);
                if (Number.isNaN(submitted.valueOf())) return;
                void onRecordEvidence(latestPackage.package_id, {
                  attempt_number: attemptNumber,
                  submitted_at: submitted.toISOString(),
                  reported_outcome: outcome,
                  report_reference: reference.trim() || undefined,
                  report_sha256: digest.trim() || undefined,
                  note: note.trim() || undefined
                });
              }}
            >
              <p className="font-semibold text-amber-100">After the manual organiser upload</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">Record reference metadata only—do not upload screenshots or paste a raw organiser report.</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="text-xs text-slate-300">Attempt (1–5)<input value={attemptNumber} min="1" max="5" type="number" onChange={(event) => setAttemptNumber(Number(event.target.value))} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" /></label>
                <label className="text-xs text-slate-300">Submitted at<input value={submittedAt} type="datetime-local" onChange={(event) => setSubmittedAt(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" /></label>
                <label className="text-xs text-slate-300">Reported outcome<select value={outcome} onChange={(event) => setOutcome(event.target.value as OrganiserReportedOutcome)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"><option value="unknown">Unknown</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option></select></label>
                <label className="text-xs text-slate-300">Report or screenshot reference<input value={reference} maxLength={500} onChange={(event) => setReference(event.target.value)} placeholder="e.g. organiser-result-1.png" className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" /></label>
              </div>
              <label className="mt-3 block text-xs text-slate-300">Optional SHA-256 digest<input value={digest} maxLength={64} onChange={(event) => setDigest(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" /></label>
              <label className="mt-3 block text-xs text-slate-300">Short note<textarea value={note} maxLength={2000} onChange={(event) => setNote(event.target.value)} className="mt-1 min-h-20 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" /></label>
              <button disabled={busy} className="mt-3 rounded-xl border border-amber-300/50 bg-amber-300/10 px-4 py-2 font-bold text-amber-100 disabled:cursor-not-allowed disabled:text-slate-500">Record metadata</button>
            </form>
          )}
        </div>
      )}
    </section>
  );
}

function CopilotButton() {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [lastPrompt, setLastPrompt] = useState("");

  return (
    <div className="fixed bottom-5 right-5 z-30">
      {open && (
        <section className="mb-3 w-80 rounded-2xl border border-cyan-300/30 bg-slate-950/95 p-4 shadow-2xl shadow-cyan-950/50 backdrop-blur">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-bold text-white">RailAccess Copilot</p>
              <p className="text-xs text-cyan-200">Grounded schedule assistant</p>
            </div>
            <button className="text-slate-400 hover:text-white" onClick={() => setOpen(false)} aria-label="Close copilot">×</button>
          </div>
          <p className="mt-4 text-sm leading-6 text-slate-300">
            Ask about a validated schedule, a hotspot or the impact of a proposed change.
          </p>
          {lastPrompt && <p className="mt-3 rounded-lg bg-slate-900 p-3 text-xs text-slate-300">Captured question: “{lastPrompt}”</p>}
          <form
            className="mt-4 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!prompt.trim()) return;
              setLastPrompt(prompt.trim());
              setPrompt("");
            }}
          >
            <input
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Ask the copilot…"
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-400"
            />
            <button className="rounded-lg bg-cyan-400 px-3 py-2 text-sm font-bold text-slate-950">Send</button>
          </form>
          <p className="mt-2 text-[11px] leading-4 text-slate-500">The Vertex/Gemini response route will be connected after solver results are available.</p>
        </section>
      )}
      <button
        onClick={() => setOpen((value) => !value)}
        className="group flex h-15 items-center gap-2 rounded-full border border-cyan-200/40 bg-slate-950/90 px-4 py-3 shadow-lg shadow-cyan-950/60 backdrop-blur transition hover:-translate-y-1 hover:border-cyan-200"
        aria-label="Open RailAccess Copilot"
      >
        <span className="text-2xl transition group-hover:translate-x-0.5">🚇</span>
        <span className="text-left text-xs font-bold uppercase tracking-[0.14em] text-cyan-100">Ask copilot</span>
      </button>
    </div>
  );
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [month, setMonth] = useState(8);
  const [year, setYear] = useState(2026);
  const [activeEvent, setActiveEvent] = useState<MaintenanceEvent | null>(null);
  const [demandFiles, setDemandFiles] = useState<File[]>([]);
  const [updateFiles, setUpdateFiles] = useState<File[]>([]);
  const [scenario, setScenario] = useState<Scenario>("A");
  const [refreshNotice, setRefreshNotice] = useState("Upload the demand book and select a scenario to prepare an optimisation run.");
  const [run, setRun] = useState<RunView | null>(null);
  const [runBusy, setRunBusy] = useState(false);

  useEffect(() => {
    railAccessApi.getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const validatorStatus = health?.validator_status ?? "checking";
  const demandBookReady = demandFiles.length === 8;
  const changeMonth = (direction: number) => {
    setMonth((current) => (current + direction + 12) % 12);
  };

  const startRun = async () => {
    if (!demandBookReady || runBusy) return;
    setRunBusy(true);
    setRun(null);
    setRefreshNotice(`Uploading the eight CSVs for Scenario ${scenario}.`);
    try {
      let current = await railAccessApi.createRun(scenario, demandFiles);
      setRun(current);
      for (let attempt = 0; attempt < 90 && (current.status === "accepted" || current.status === "running"); attempt += 1) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 1000));
        current = await railAccessApi.getRun(current.run_id);
        setRun(current);
      }
      setRefreshNotice(`Scenario ${scenario} run is ${current.status}. Review its local evidence below.`);
      setDemandFiles([]);
    } catch (error) {
      const detail = error instanceof RailAccessApiError ? error.message : "The run could not be started.";
      setRefreshNotice(detail);
    } finally {
      setRunBusy(false);
    }
  };

  const createSubmissionPackage = async () => {
    if (!run || runBusy) return;
    setRunBusy(true);
    try {
      const submissionPackage = await railAccessApi.createSubmissionPackage(run.run_id);
      setRun((current) => current ? { ...current, submission_packages: [...current.submission_packages, submissionPackage] } : current);
      setRefreshNotice("Manual upload ZIP created. Download it, submit it on the organiser website, then record reference metadata.");
    } catch (error) {
      setRefreshNotice(error instanceof RailAccessApiError ? error.message : "Could not create the submission package.");
    } finally {
      setRunBusy(false);
    }
  };

  const recordEvidence = async (packageId: string, payload: OrganiserEvidenceInput) => {
    if (!run || runBusy) return;
    setRunBusy(true);
    try {
      const updatedPackage = await railAccessApi.recordOrganiserEvidence(run.run_id, packageId, payload);
      setRun((current) => current ? {
        ...current,
        submission_packages: current.submission_packages.map((item) => item.package_id === packageId ? updatedPackage : item)
      } : current);
      setRefreshNotice("Organiser metadata was recorded for this live run. Download the evidence JSON and keep it outside the repository.");
    } catch (error) {
      setRefreshNotice(error instanceof RailAccessApiError ? error.message : "Could not record organiser metadata.");
    } finally {
      setRunBusy(false);
    }
  };

  return (
    <main className="rail-editorial relative min-h-screen overflow-hidden px-4 py-6 text-slate-100 sm:px-8 sm:py-8">
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 opacity-35">
        <TrainScene />
      </div>
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-[1]">
        {stars.map(([left, top, size, delay]) => (
          <span key={`${left}-${top}`} className="twinkle-star" style={{ left, top, width: size, height: size, animationDelay: delay }} />
        ))}
      </div>

      <section className="relative z-10 mx-auto max-w-7xl pb-28">
        <header className="editorial-hero flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="editorial-title text-3xl font-black tracking-tight text-white sm:text-5xl">MAINTENANCE SCHEDULE PLANNER</h1>
          </div>
          <div className="flex flex-wrap gap-2 text-sm">
            <span className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 font-semibold text-cyan-200">API {health?.status ?? "connecting"}</span>
            <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-3 py-1.5 font-semibold text-amber-100">Validator: {validatorStatus}</span>
          </div>
        </header>

        <div className="mt-7 grid gap-5 xl:grid-cols-[1.08fr_0.92fr]">
          <TrackDiagram activeStation={activeEvent?.station ?? null} />
          <Calendar
            month={month}
            year={year}
            activeEvent={activeEvent}
            onMonthChange={changeMonth}
            onYearChange={(direction) => setYear((current) => current + direction)}
            onEventHover={setActiveEvent}
          />
        </div>

        <section className="mt-5 grid gap-5 lg:grid-cols-[1fr_1fr_0.8fr]">
          <div className="editorial-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">03 · Build schedule</p>
            <h2 className="mt-1 text-xl font-bold text-white">Demand-book upload</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">Drag in all eight official CSVs for the scheduling pipeline.</p>
            <div className="mt-4">
              <UploadDropzone
                id="demand-book"
                title="Official demand book"
                description="01_LINES through 08_ACTIVITY_DETAILS · CSV only"
                files={demandFiles}
                multiple
                onFiles={setDemandFiles}
              />
            </div>
            <p className={`mt-3 text-xs font-semibold ${demandBookReady ? "text-emerald-300" : "text-slate-500"}`}>
              {demandBookReady ? "Demand book complete — ready for validation." : `${Math.max(0, 8 - demandFiles.length)} of 8 required files still needed.`}
            </p>
          </div>

          <div className="editorial-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">04 · Update event</p>
            <h2 className="mt-1 text-xl font-bold text-white">Disruption upload</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">Provide a single event CSV to adjust supply or introduce urgent work.</p>
            <div className="mt-4">
              <UploadDropzone
                id="update-event"
                title="Updated event CSV"
                description="One approved scenario change · CSV only"
                files={updateFiles}
                multiple={false}
                onFiles={setUpdateFiles}
              />
            </div>
            <p className="mt-3 text-xs text-slate-500">Confirmed work will remain locked when the recovery optimiser is connected.</p>
          </div>

          <div className="editorial-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">05–06 · Optimise</p>
            <h2 className="mt-1 text-xl font-bold text-white">Scenario control</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">Choose the objective before running a schedule refresh.</p>
            <div className="mt-4 grid grid-cols-3 gap-2">
              {(["A", "B", "C"] as Scenario[]).map((option) => (
                <button
                  key={option}
                  onClick={() => setScenario(option)}
                  className={`rounded-lg border px-2 py-3 text-sm font-black transition ${scenario === option ? "border-cyan-300 bg-cyan-300 text-slate-950 shadow-lg shadow-cyan-400/20" : "border-slate-700 bg-slate-900 text-slate-300 hover:border-cyan-500"}`}
                >
                  {option}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">A: strict supply · B: strict schedule · C: balanced</p>
            <button
              disabled={!demandBookReady || runBusy}
              onClick={() => void startRun()}
              className="mt-5 w-full rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {runBusy ? "Running schedule…" : "Run schedule"}
            </button>
            <p className="mt-3 text-xs leading-5 text-slate-400">{refreshNotice}</p>
          </div>
        </section>
        <SubmissionEvidencePanel
          run={run}
          busy={runBusy}
          notice=""
          onCreatePackage={createSubmissionPackage}
          onRecordEvidence={recordEvidence}
        />
      </section>
      <CopilotButton />
    </main>
  );
}
