import { useEffect, useMemo, useState } from "react";
import { TrainScene } from "./TrainScene";

type Health = {
  status: string;
  validator_status: string;
};

type Scenario = "A" | "B" | "C";

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

  const stationNode = (name: string, x: number, y: number, colour: string) => {
    const active = name === activeStation;
    return (
      <g key={name}>
        {active && <circle cx={x} cy={y} r="19" fill={colour} opacity="0.18" />}
        <circle cx={x} cy={y} r={active ? "10" : "8"} fill="#111827" stroke={colour} strokeWidth={active ? "5" : "3"} />
        <text x={x} y={y - 26} textAnchor="middle" fill={active ? "#f8fafc" : "#e2e8f0"} fontSize="15" fontWeight="700">{name}</text>
      </g>
    );
  };

  return (
    <section className="rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
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

      <svg className="mt-4 h-auto w-full" viewBox="0 0 1000 330" role="img" aria-label="Metro Line Alpha and Metro Line Beta directional access topology">
        <defs>
          <marker id="alp-arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#e45850" />
          </marker>
          <marker id="bet-arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#63c38a" />
          </marker>
        </defs>

        <rect x="650" y="4" width="330" height="48" rx="10" fill="#1e293b" stroke="#334155" />
        <text x="666" y="25" fill="#cbd5e1" fontSize="13" fontWeight="700">Directional bounds</text>
        <line x1="790" y1="21" x2="864" y2="21" stroke="#69baf0" strokeWidth="3" markerEnd="url(#alp-arrow)" />
        <text x="878" y="26" fill="#93c5fd" fontSize="12" fontWeight="700">EB</text>
        <line x1="864" y1="38" x2="790" y2="38" stroke="#69baf0" strokeWidth="3" markerEnd="url(#alp-arrow)" />
        <text x="878" y="43" fill="#93c5fd" fontSize="12" fontWeight="700">WB</text>

        <rect x="10" y="96" width="60" height="28" rx="6" fill="#df5750" />
        <text x="40" y="115" textAnchor="middle" fill="#ffffff" fontSize="14" fontWeight="800">ALP</text>
        <text x="82" y="115" fill="#f8b4b1" fontSize="14" fontWeight="700">Metro Line Alpha · Red line</text>
        <line x1="315" y1="105" x2="940" y2="105" stroke="#e45850" strokeWidth="5" markerEnd="url(#alp-arrow)" />
        <line x1="940" y1="130" x2="315" y2="130" stroke="#e45850" strokeWidth="4" strokeDasharray="7 5" markerEnd="url(#alp-arrow)" />
        <text x="948" y="109" fill="#fca5a5" fontSize="12" fontWeight="700">EB</text>
        <text x="280" y="134" fill="#fca5a5" fontSize="12" fontWeight="700">WB</text>

        {alphaStations.map((station, index) => stationNode(station, stationPositions[index], 118, "#e45850"))}
        {["H01", "H02"].map((name, index) => {
          const x = index === 0 ? 610 : 670;
          const active = activeStation === name;
          return (
            <g key={name}>
              {active && <rect x={x - 18} y="88" width="36" height="58" rx="7" fill="#fbbf24" opacity="0.25" />}
              <rect x={x - 12} y="94" width="24" height="44" rx="5" fill={active ? "#fbbf24" : "#b78736"} stroke="#f4c15c" strokeWidth={active ? "3" : "2"} />
              <text x={x} y="88" textAnchor="middle" fill="#f8d47a" fontSize="14" fontWeight="800">{name}</text>
            </g>
          );
        })}

        <rect x="10" y="238" width="60" height="28" rx="6" fill="#5fc486" />
        <text x="40" y="257" textAnchor="middle" fill="#ffffff" fontSize="14" fontWeight="800">BET</text>
        <text x="82" y="257" fill="#b7efca" fontSize="14" fontWeight="700">Metro Line Beta · Green line</text>
        <line x1="315" y1="248" x2="940" y2="248" stroke="#63c38a" strokeWidth="5" markerEnd="url(#bet-arrow)" />
        <line x1="940" y1="273" x2="315" y2="273" stroke="#63c38a" strokeWidth="4" strokeDasharray="7 5" markerEnd="url(#bet-arrow)" />
        <text x="948" y="252" fill="#a7f3c0" fontSize="12" fontWeight="700">EB</text>
        <text x="280" y="277" fill="#a7f3c0" fontSize="12" fontWeight="700">WB</text>
        {betaStations.map((station, index) => stationNode(station, stationPositions[index], 260, "#63c38a"))}
        {["H01", "H02"].map((name, index) => {
          const x = index === 0 ? 610 : 670;
          const active = activeStation === name;
          return (
            <g key={name}>
              {active && <rect x={x - 18} y="226" width="36" height="58" rx="7" fill="#fbbf24" opacity="0.25" />}
              <rect x={x - 12} y="232" width="24" height="44" rx="5" fill={active ? "#fbbf24" : "#b78736"} stroke="#f4c15c" strokeWidth={active ? "3" : "2"} />
              <text x={x} y="304" textAnchor="middle" fill="#f8d47a" fontSize="14" fontWeight="800">{name}</text>
            </g>
          );
        })}
      </svg>
      <p className="mt-2 text-xs leading-5 text-slate-400">
        Each line keeps independent EB/WB bounds. H01 and H02 are controlled access points.
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
    <section className="rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
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
            <div key={day} className="calendar-day">
              <span>{day}</span>
              {event && (
                <button
                  aria-label={event.title}
                  className={`calendar-event ${event.colour}`}
                  onMouseEnter={() => onEventHover(event)}
                  onFocus={() => onEventHover(event)}
                  onMouseLeave={() => onEventHover(null)}
                  onBlur={() => onEventHover(null)}
                />
              )}
            </div>
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
          <p className="text-sm text-slate-400">Hover a coloured maintenance marker for location, time and crew details.</p>
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
  const [scenario, setScenario] = useState<Scenario>("C");
  const [refreshNotice, setRefreshNotice] = useState("Upload the demand book and select a scenario to prepare an optimisation run.");

  useEffect(() => {
    fetch("/api/health")
      .then((response) => response.json() as Promise<Health>)
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const validatorStatus = health?.validator_status ?? "checking";
  const demandBookReady = demandFiles.length === 8;
  const monthLabel = useMemo(() => `${months[month]} ${year}`, [month, year]);

  const changeMonth = (direction: number) => {
    setMonth((current) => (current + direction + 12) % 12);
  };

  return (
    <main className="night-sky relative min-h-screen overflow-hidden px-4 py-6 text-slate-100 sm:px-8 sm:py-8">
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 opacity-70">
        <TrainScene />
      </div>
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-[1]">
        {stars.map(([left, top, size, delay]) => (
          <span key={`${left}-${top}`} className="twinkle-star" style={{ left, top, width: size, height: size, animationDelay: delay }} />
        ))}
      </div>

      <section className="relative z-10 mx-auto max-w-7xl pb-28">
        <header className="flex flex-col gap-5 border-b border-slate-700/80 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex items-center gap-3 text-xs font-bold uppercase tracking-[0.24em] text-cyan-300">
              <span className="h-px w-9 bg-cyan-400" />
              RailAccess AI · Planner console
            </div>
            <h1 className="mt-3 text-3xl font-black tracking-tight text-white sm:text-5xl">Plan the night. Protect the first train.</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
              An explainable control room for possession planning across the Alpha and Beta rail lines.
            </p>
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
          <div className="rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
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

          <div className="rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
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

          <div className="rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
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
              disabled={!demandBookReady}
              onClick={() => setRefreshNotice(`Preview refreshed for Scenario ${scenario} in ${monthLabel}. The optimiser endpoint will replace this demo state with a validated schedule.`)}
              className="mt-5 w-full rounded-xl bg-cyan-400 px-4 py-3 font-bold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              Update optimal schedule
            </button>
            <p className="mt-3 text-xs leading-5 text-slate-400">{refreshNotice}</p>
          </div>
        </section>
      </section>
      <CopilotButton />
    </main>
  );
}
