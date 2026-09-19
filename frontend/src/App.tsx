import { useEffect, useState } from "react";
import { forRailsApi, ForRailsApiError } from "./api/client";
import type { CapabilityReport, Health, RunView, Scenario, ScenarioChangeDraft, ScenarioChangeDraftUpdate } from "./api/types";
import { TrainScene } from "./TrainScene";
import { GroundedCopilot } from "./GroundedCopilot";
import { RecoverySandbox } from "./RecoverySandbox";

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

type PlannerPage = "overview" | "setup";
type CalendarView = "month" | "week" | "day";

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
    colour: "bg-red-500"
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
  ["3%", "28%", 1, "1.7s"], ["5%", "12%", 2, "0s"], ["7%", "77%", 2, "2.5s"],
  ["10%", "57%", 1, "0.8s"], ["12%", "42%", 3, "1.4s"], ["14%", "91%", 1, "2.2s"],
  ["18%", "19%", 2, "2.1s"], ["20%", "63%", 1, "0.2s"], ["22%", "35%", 2, "3s"],
  ["24%", "70%", 3, "0.6s"], ["27%", "48%", 1, "1.9s"], ["29%", "88%", 2, "1.2s"],
  ["31%", "9%", 2, "2.8s"], ["34%", "27%", 1, "0.5s"], ["36%", "75%", 2, "2.3s"],
  ["38%", "55%", 2, "1.1s"], ["41%", "13%", 1, "2.7s"], ["44%", "31%", 3, "2.4s"],
  ["46%", "67%", 1, "0.9s"], ["49%", "86%", 2, "1.6s"], ["51%", "15%", 2, "0.3s"],
  ["54%", "49%", 1, "2.9s"], ["57%", "76%", 3, "1.8s"], ["59%", "25%", 2, "0.7s"],
  ["61%", "92%", 1, "2s"], ["63%", "43%", 2, "2.6s"], ["66%", "61%", 1, "1.3s"],
  ["69%", "7%", 3, "0.9s"], ["71%", "34%", 1, "2.1s"], ["73%", "83%", 2, "0.4s"],
  ["75%", "63%", 2, "1.5s"], ["78%", "14%", 1, "2.8s"], ["80%", "54%", 2, "1s"],
  ["82%", "26%", 3, "2.9s"], ["85%", "71%", 1, "0.1s"], ["87%", "38%", 2, "2.4s"],
  ["89%", "48%", 2, "0.5s"], ["91%", "88%", 1, "1.8s"], ["94%", "17%", 3, "2s"],
  ["97%", "65%", 2, "1.1s"], ["1%", "47%", 1, "0.6s"], ["4%", "5%", 1, "2.6s"],
  ["6%", "94%", 1, "1.1s"], ["9%", "31%", 1, "2.2s"], ["11%", "68%", 1, "0.4s"],
  ["13%", "4%", 1, "1.5s"], ["15%", "52%", 1, "2.9s"], ["17%", "82%", 1, "0.7s"],
  ["19%", "44%", 1, "1.8s"], ["21%", "6%", 1, "0.3s"], ["23%", "96%", 1, "2.4s"],
  ["25%", "18%", 1, "1.4s"], ["26%", "59%", 1, "0.1s"], ["28%", "39%", 1, "2.7s"],
  ["30%", "74%", 1, "0.9s"], ["32%", "47%", 1, "2s"], ["33%", "19%", 1, "1.2s"],
  ["35%", "93%", 1, "2.5s"], ["37%", "36%", 1, "0.5s"], ["39%", "65%", 1, "1.7s"],
  ["40%", "5%", 1, "2.3s"], ["42%", "81%", 1, "0.8s"], ["43%", "46%", 1, "1.9s"],
  ["45%", "22%", 1, "0.2s"], ["47%", "94%", 1, "2.8s"], ["48%", "57%", 1, "1s"],
  ["50%", "38%", 1, "2.1s"], ["52%", "73%", 1, "0.4s"], ["53%", "4%", 1, "1.6s"],
  ["55%", "31%", 1, "2.6s"], ["56%", "91%", 1, "0.7s"], ["58%", "56%", 1, "1.4s"],
  ["60%", "18%", 1, "0.1s"], ["62%", "81%", 1, "2.5s"], ["64%", "30%", 1, "1.2s"],
  ["65%", "96%", 1, "1.9s"], ["67%", "51%", 1, "0.5s"], ["68%", "15%", 1, "2.7s"],
  ["70%", "69%", 1, "0.8s"], ["72%", "44%", 1, "1.7s"], ["74%", "97%", 1, "2.2s"],
  ["76%", "36%", 1, "0.3s"], ["77%", "79%", 1, "2.9s"], ["79%", "3%", 1, "1.1s"],
  ["81%", "59%", 1, "2s"], ["83%", "92%", 1, "0.6s"], ["84%", "11%", 1, "1.5s"],
  ["86%", "47%", 1, "2.4s"], ["88%", "76%", 1, "0.9s"], ["90%", "29%", 1, "1.8s"],
  ["92%", "58%", 1, "0.2s"], ["93%", "4%", 1, "2.6s"], ["95%", "83%", 1, "1.3s"],
  ["96%", "41%", 1, "2.1s"], ["98%", "9%", 1, "0.7s"], ["99%", "92%", 1, "1.6s"]
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
    <section className="editorial-card c151-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">Network view</p>
          <h2 className="section-heading mt-1 text-xl font-bold leading-tight text-white">Tracks overview</h2>
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
  const [view, setView] = useState<CalendarView>("month");
  const [focusedDay, setFocusedDay] = useState(1);
  // Use UTC so the official Gregorian layout is never shifted by a browser timezone.
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const selectedDay = Math.min(focusedDay, daysInMonth);
  const focusedDate = new Date(Date.UTC(year, month, selectedDay));
  const firstWeekday = new Date(Date.UTC(year, month, 1)).getUTCDay();
  const leadingBlanks = Array.from({ length: firstWeekday }, (_, index) => index);
  const calendarDays = Array.from({ length: daysInMonth }, (_, index) => index + 1);
  const weekStart = new Date(Date.UTC(year, month, selectedDay - focusedDate.getUTCDay()));
  const weekDates = Array.from({ length: 7 }, (_, index) => new Date(Date.UTC(
    weekStart.getUTCFullYear(),
    weekStart.getUTCMonth(),
    weekStart.getUTCDate() + index
  )));
  const daySlots = Array.from({ length: 24 }, (_, index) => {
    const minutes = index * 15;
    return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  });

  const eventForDay = (day: number) => maintenanceEvents.find(
    (event) => event.day === day && event.month === month && event.year === year
  );
  const eventForDate = (date: Date) => maintenanceEvents.find(
    (event) => event.day === date.getUTCDate()
      && event.month === date.getUTCMonth()
      && event.year === date.getUTCFullYear()
  );
  const focusedEvents = maintenanceEvents.filter(
    (event) => event.day === selectedDay && event.month === month && event.year === year
  );
  const eventHandlers = (event: MaintenanceEvent) => ({
    onMouseEnter: () => onEventHover(event),
    onFocus: () => onEventHover(event),
    onMouseLeave: () => onEventHover(null),
    onBlur: () => onEventHover(null),
  });
  const moveFocusedDate = (days: number) => {
    const nextDate = new Date(Date.UTC(year, month, selectedDay + days));
    const monthOffset = (nextDate.getUTCFullYear() - year) * 12 + nextDate.getUTCMonth() - month;
    if (monthOffset) onMonthChange(monthOffset);
    setFocusedDay(nextDate.getUTCDate());
  };
  const selectDate = (date: Date) => {
    const monthOffset = (date.getUTCFullYear() - year) * 12 + date.getUTCMonth() - month;
    if (monthOffset) onMonthChange(monthOffset);
    setFocusedDay(date.getUTCDate());
  };
  const eventGridRow = (event: MaintenanceEvent) => {
    const [startValue, endValue] = event.time.split("–");
    const toMinutes = (value: string) => {
      const [hours, minutes] = value.split(":").map(Number);
      return hours * 60 + minutes;
    };
    const startSlot = Math.max(0, Math.floor(toMinutes(startValue) / 15));
    const endSlot = Math.min(daySlots.length, Math.ceil(toMinutes(endValue) / 15));
    return `${startSlot + 1} / ${Math.max(startSlot + 2, endSlot + 1)}`;
  };

  return (
    <section className="editorial-card c151-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">Maintenance calendar</p>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
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
        <div className="flex rounded-lg border border-slate-700 bg-slate-950/80 p-0.5" aria-label="Calendar view">
          {(["day", "week", "month"] as CalendarView[]).map((option) => (
            <button
              key={option}
              onClick={() => setView(option)}
              className={`rounded-md px-2.5 py-1 text-xs font-bold capitalize transition ${view === option ? "bg-red-500 text-white shadow-sm" : "text-slate-400 hover:text-slate-100"}`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      {view !== "month" && (
        <div className="mt-3 flex items-center justify-between rounded-lg border border-slate-700 bg-slate-950/60 px-2 py-1.5">
          <button className="calendar-arrow" onClick={() => moveFocusedDate(view === "week" ? -7 : -1)} aria-label={view === "week" ? "Previous week" : "Previous day"}>←</button>
          <span className="text-center text-xs font-bold text-slate-200">
            {view === "week"
              ? `${months[weekDates[0].getUTCMonth()].slice(0, 3)} ${weekDates[0].getUTCDate()} – ${months[weekDates[6].getUTCMonth()].slice(0, 3)} ${weekDates[6].getUTCDate()}`
              : `${months[month]} ${selectedDay}, ${year}`}
          </span>
          <button className="calendar-arrow" onClick={() => moveFocusedDate(view === "week" ? 7 : 1)} aria-label={view === "week" ? "Next week" : "Next day"}>→</button>
        </div>
      )}

      {view === "month" && (
        <div className="mt-5 grid grid-cols-7 gap-1 text-center text-xs">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => (
            <span key={day} className="pb-1 text-slate-500">{day}</span>
          ))}
          {leadingBlanks.map((index) => (
            <span key={`empty-${index}`} className="calendar-blank" aria-hidden="true" />
          ))}
          {calendarDays.map((day) => {
            const event = eventForDay(day);
            return (
              <button
                key={`date-${day}`}
                aria-label={event ? `${day} ${months[month]}: ${event.title}` : `${day} ${months[month]}`}
                className={`calendar-day calendar-event-date ${day === selectedDay ? "bg-slate-800/70 ring-1 ring-slate-600" : ""}`}
                onClick={() => setFocusedDay(day)}
                {...(event ? eventHandlers(event) : {})}
              >
                <span className="font-bold">{day}</span>
                {event && <span className={`calendar-event ${event.colour}`} aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}

      {view === "week" && (
        <div className="mt-5 grid grid-cols-7 overflow-hidden rounded-xl border border-slate-700 bg-slate-950/70 text-center">
          {weekDates.map((date) => {
            const event = eventForDate(date);
            const isFocused = date.getUTCFullYear() === year && date.getUTCMonth() === month && date.getUTCDate() === selectedDay;
            return (
              <div key={date.toISOString()} className={`min-h-32 border-r border-slate-800 px-1 py-2 last:border-r-0 ${isFocused ? "bg-slate-800/70" : ""}`}>
                <p className="text-[10px] font-bold uppercase text-slate-500">{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][date.getUTCDay()]}</p>
                <p className="mt-1 text-sm font-bold text-white">{date.getUTCDate()}</p>
                {event && (
                  <button {...eventHandlers(event)} onClick={() => selectDate(date)} className={`mt-3 w-full rounded-md ${event.colour} px-1 py-2 text-left text-[10px] font-bold leading-tight text-white shadow-sm`}>
                    <span className="block opacity-80">{event.time}</span>
                    <span className="mt-1 block">{event.title}</span>
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {view === "day" && (
        <div className="mt-5 overflow-hidden rounded-xl border border-slate-700 bg-slate-950/70">
          <div className="border-b border-slate-700 px-3 py-2 text-sm font-bold text-white">
            {["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][focusedDate.getUTCDay()]}, {months[month]} {selectedDay}
          </div>
          <div className="grid grid-cols-[3.7rem_1fr]">
            <div className="grid border-r border-slate-800" style={{ gridTemplateRows: "repeat(24, minmax(1.25rem, auto))" }}>
              {daySlots.map((slot, index) => (
                <span key={slot} className="border-b border-slate-800/80 px-2 pt-0.5 text-[10px] font-semibold text-slate-500" style={{ gridRow: index + 1, gridColumn: 1 }}>
                  {slot.endsWith(":00") ? slot : ""}
                </span>
              ))}
            </div>
            <div className="grid p-1.5" style={{ gridTemplateRows: "repeat(24, minmax(1.25rem, auto))" }}>
              {daySlots.map((slot, index) => (
                <span key={slot} className="border-b border-slate-800/80" style={{ gridRow: index + 1, gridColumn: 1 }} />
              ))}
              {focusedEvents.map((event) => (
                <button
                  key={event.id}
                  {...eventHandlers(event)}
                  className={`z-10 m-0.5 rounded-md ${event.colour} px-2 py-1 text-left text-xs font-bold text-white shadow-sm`}
                  style={{ gridRow: eventGridRow(event), gridColumn: 1 }}
                >
                  {event.title} <span className="font-medium opacity-85">· {event.time}</span>
                </button>
              ))}
              {!focusedEvents.length && <p className="z-10 row-span-24 self-center px-3 text-sm text-slate-500">No scheduled maintenance for this day.</p>}
            </div>
          </div>
        </div>
      )}

      <div className="mt-5 rounded-xl border border-slate-700 bg-slate-900/80 p-3">
        {activeEvent ? (
          <div>
            <p className="font-semibold text-white">{activeEvent.title}</p>
            <p className="mt-1 text-sm text-red-200">{activeEvent.station} · {activeEvent.line} · {activeEvent.time}</p>
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
      className={`block cursor-pointer rounded-xl border border-dashed p-4 transition ${dragging ? "border-red-400 bg-red-500/10" : "border-slate-600 bg-slate-900/60 hover:border-red-500/70"}`}
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
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-red-500/15 text-xl text-red-200">↓</span>
        <div>
          <p className="font-semibold text-white">{title}</p>
          <p className="mt-1 text-xs leading-5 text-slate-400">{description}</p>
          <p className="mt-2 text-xs font-semibold text-red-200">
            {files.length ? `${files.length} CSV file${files.length === 1 ? "" : "s"} selected` : "Drop CSV files here or browse"}
          </p>
        </div>
      </div>
    </label>
  );
}

const publicScheduleFiles = [
  { name: "SCHEDULE_ACCESS.csv", description: "Activity access placement by week" },
  { name: "SCHEDULE_OCCUPANCY.csv", description: "Location and slot assignments" },
  { name: "RESULTS.csv", description: "Contract completion summary" }
] as const;

function PublicScheduleDownloads() {
  return (
    <section className="editorial-card c151-card mt-5 rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">Download</p>
      <div className="mt-1 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h2 className="section-heading mt-1 text-xl font-bold leading-tight text-white">Schedule files</h2>
          <p className="mt-1 text-sm text-slate-400">Download the schedules for the provided dataset.</p>
        </div>
        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">CSV · Scenario A</span>
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-3">
        {publicScheduleFiles.map((file) => (
          <a
            key={file.name}
            href={forRailsApi.getPublicScheduleUrl(file.name)}
            className="group rounded-xl border border-slate-700 bg-slate-900/70 p-3 transition hover:border-red-400 hover:bg-red-500/10"
          >
            <p className="font-mono text-sm font-bold text-white">{file.name}</p>
            <p className="mt-1 text-xs text-slate-400">{file.description}</p>
            <p className="mt-3 text-xs font-bold text-red-200 group-hover:text-red-100">Download CSV ↓</p>
          </a>
        ))}
      </div>
    </section>
  );
}

function RecoveryOutcome({ run }: { run: RunView | null }) {
  const diff = run?.schedule_diff;
  if (!run || run.demo || !diff) return null;
  const diagnostics = run.solver_diagnostics;
  const changed = diff.placement_changes.filter((item) => item.kind !== "unchanged");
  const label = diagnostics?.recovery_source === "reoptimized"
    ? "Re-optimised"
    : diagnostics?.recovery_source === "incumbent_not_worse"
      ? "Kept equally good incumbent"
      : diagnostics?.recovery_source === "incumbent_fallback"
        ? "Safe incumbent fallback"
        : "Recovery result";

  return (
    <section className="editorial-card c151-card mt-5 rounded-2xl border border-emerald-300/30 bg-emerald-300/5 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-200">Recovery outcome</p>
          <h2 className="section-heading mt-1 text-xl font-bold text-white">{label}</h2>
          <p className="mt-1 text-sm leading-6 text-slate-300">Scenario C was compared with its baseline under the confirmed change. This local result remains unverified until the organiser checks these exact exports.</p>
        </div>
        <span className="rounded-full border border-emerald-300/35 bg-emerald-300/10 px-3 py-1 text-xs font-bold text-emerald-100">{run.validation_report?.status ?? "unverified"}</span>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-700 bg-slate-950/55 p-3"><p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Moved work</p><p className="mt-1 text-2xl font-bold text-white">{diff.moved_count}</p><p className="text-xs text-slate-400">placements changed</p></div>
        <div className="rounded-xl border border-slate-700 bg-slate-950/55 p-3"><p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Kept work</p><p className="mt-1 text-2xl font-bold text-white">{diff.unchanged_count}</p><p className="text-xs text-slate-400">placements unchanged</p></div>
        <div className="rounded-xl border border-slate-700 bg-slate-950/55 p-3"><p className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Solver</p><p className="mt-1 text-lg font-bold text-white">{diagnostics?.status ?? "Recorded"}</p><p className="text-xs text-slate-400">{diagnostics ? `${diagnostics.wall_time_seconds.toFixed(1)}s of ${diagnostics.time_limit_seconds}s` : "execution details unavailable"}</p></div>
      </div>
      {changed.length > 0 && <div className="mt-4 rounded-xl border border-slate-700 bg-slate-950/55 p-3"><p className="text-xs font-bold uppercase tracking-wider text-slate-400">Changed placements</p><ul className="mt-2 max-h-36 space-y-1 overflow-y-auto text-xs text-slate-300">{changed.slice(0, 25).map((item) => <li key={`${item.key.activity_id}-${item.key.access_seq}`}><b>{item.key.activity_id}</b> access {item.key.access_seq}: {item.kind}{item.changed_fields.length ? ` (${item.changed_fields.join(", ")})` : ""}</li>)}</ul>{changed.length > 25 && <p className="mt-2 text-xs text-slate-500">Showing 25 of {changed.length} changed placements.</p>}</div>}
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
        <section className="mb-3 w-80 rounded-2xl border border-red-400/30 bg-slate-950/95 p-4 shadow-2xl shadow-red-950/50 backdrop-blur">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-bold text-white">For Rails Copilot</p>
              <p className="text-xs text-red-200">Grounded schedule assistant</p>
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
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-red-500"
            />
            <button className="rounded-lg bg-red-500 px-3 py-2 text-sm font-bold text-white">Send</button>
          </form>
          <p className="mt-2 text-[11px] leading-4 text-slate-500">The Vertex/Gemini response route will be connected after solver results are available.</p>
        </section>
      )}
      <button
        onClick={() => setOpen((value) => !value)}
        className="group flex h-15 items-center gap-2 rounded-full border border-red-200/40 bg-slate-950/90 px-4 py-3 shadow-lg shadow-red-950/60 backdrop-blur transition hover:-translate-y-1 hover:border-red-200"
        aria-label="Open For Rails Copilot"
      >
        <span className="text-2xl transition group-hover:translate-x-0.5">🚇</span>
        <span className="text-left text-xs font-bold uppercase tracking-[0.14em] text-red-100">Ask copilot</span>
      </button>
    </div>
  );
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityReport | null>(null);
  const [month, setMonth] = useState(8);
  const [year, setYear] = useState(2026);
  const [activeEvent, setActiveEvent] = useState<MaintenanceEvent | null>(null);
  const [demandFiles, setDemandFiles] = useState<File[]>([]);
  const [scenario, setScenario] = useState<Scenario>("A");
  const [page, setPage] = useState<PlannerPage>("overview");
  const [refreshNotice, setRefreshNotice] = useState("Upload the eight CSV demand book, then select an available scenario to prepare an optimisation run.");
  const [run, setRun] = useState<RunView | null>(null);
  const [runBusy, setRunBusy] = useState(false);

  useEffect(() => {
    forRailsApi.getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
    forRailsApi.getCapabilities()
      .then(setCapabilities)
      .catch(() => setCapabilities(null));
  }, []);

  const validatorStatus = health?.validator_status ?? "checking";
  const demandBookReady = demandFiles.length === 8;
  const scheduleInputReady = demandBookReady;
  const changeMonth = (direction: number) => {
    const nextDate = new Date(Date.UTC(year, month + direction, 1));
    setMonth(nextDate.getUTCMonth());
    setYear(nextDate.getUTCFullYear());
  };

  const startRun = async () => {
    if (!scheduleInputReady || runBusy) return;
    const scenarioCapability = capabilities?.scenarios.find((item) => item.scenario === scenario);
    if (!scenarioCapability?.available) {
      setRefreshNotice(scenarioCapability?.message ?? "Checking the active solver capabilities. Please try again in a moment.");
      return;
    }
    setRunBusy(true);
    setRun(null);
    const runFiles = demandFiles;
    setRefreshNotice(`Uploading the eight CSV demand book for Scenario ${scenario}.`);
    try {
      let current = await forRailsApi.createRun(scenario, runFiles);
      setRun(current);
      for (let attempt = 0; attempt < 330 && (current.status === "accepted" || current.status === "running"); attempt += 1) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 1000));
        current = await forRailsApi.getRun(current.run_id);
        setRun(current);
      }
      const diagnostics = current.solver_diagnostics;
      const solverEvidence = diagnostics
        ? ` CP-SAT ${diagnostics.status} in ${diagnostics.wall_time_seconds.toFixed(1)}s of ${diagnostics.time_limit_seconds}s.`
        : "";
      setRefreshNotice(`Scenario ${scenario} run is ${current.status}. Review its local evidence below.${solverEvidence}`);
      setDemandFiles([]);
      setPage("overview");
    } catch (error) {
      const detail = error instanceof ForRailsApiError ? error.message : "The run could not be started.";
      setRefreshNotice(detail);
    } finally {
      setRunBusy(false);
    }
  };

  const openPublicDemo = async () => {
    if (runBusy) return;
    setRunBusy(true);
    try {
      const demo = await forRailsApi.createPublicDemoRun();
      setRun(demo);
      setRefreshNotice("Public recovery demonstration loaded. It is unverified and cannot be exported or submitted.");
      setPage("overview");
    } catch (error) {
      setRefreshNotice(error instanceof ForRailsApiError ? error.message : "Could not open the public recovery demonstration.");
    } finally {
      setRunBusy(false);
    }
  };

  const replayPublicDemo = async (draftId?: string) => {
    if (!run || runBusy) return;
    setRunBusy(true);
    try {
      setRun(await forRailsApi.createPublicDemoReplay(run.run_id, draftId));
    } finally {
      setRunBusy(false);
    }
  };

  const createDisruptionDraft = async (text: string): Promise<ScenarioChangeDraft> => {
    if (!run) throw new Error("Open the public recovery demonstration first.");
    return forRailsApi.createDisruptionDraft(run.run_id, text);
  };

  const createSupplyCsvDraft = async (file: File): Promise<ScenarioChangeDraft> => {
    if (!run) throw new Error("Run a schedule before reviewing replacement supply data.");
    return forRailsApi.createSupplyCsvDraft(run.run_id, file);
  };

  const updateRecoveryDraft = async (draftId: string, payload: ScenarioChangeDraftUpdate): Promise<ScenarioChangeDraft> => {
    if (!run) throw new Error("Run a schedule before editing a recovery draft.");
    return forRailsApi.updateRecoveryDraft(run.run_id, draftId, payload);
  };

  const confirmRecoveryDraft = async (draftId: string) => {
    if (!run || runBusy) return;
    setRunBusy(true);
    try {
      let current = await forRailsApi.confirmRecoveryDraft(run.run_id, draftId);
      setRun(current);
      setRefreshNotice("Scenario C recovery is running with the confirmed controller changes.");
      for (let attempt = 0; attempt < 330 && (current.status === "accepted" || current.status === "running"); attempt += 1) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 1000));
        current = await forRailsApi.getRun(current.run_id);
        setRun(current);
      }
      const diagnostics = current.solver_diagnostics;
      const evidence = diagnostics
        ? ` CP-SAT ${diagnostics.status} in ${diagnostics.wall_time_seconds.toFixed(1)}s of ${diagnostics.time_limit_seconds}s.`
        : "";
      setRefreshNotice(`Scenario C recovery is ${current.status}.${evidence}`);
    } catch (error) {
      setRefreshNotice(error instanceof ForRailsApiError ? error.message : "Recovery could not be started.");
    } finally {
      setRunBusy(false);
    }
  };

  return (
    <main className="rail-editorial relative min-h-screen overflow-hidden px-3 py-3 text-slate-100 sm:px-5 sm:py-5">
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-[1]">
        <TrainScene />
      </div>
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-0">
        {stars.map(([left, top, size, delay]) => (
          <span key={`${left}-${top}`} className="twinkle-star" style={{ left, top, width: size, height: size, animationDelay: delay }} />
        ))}
      </div>

      <section className="relative z-10 mx-auto max-w-7xl pb-20">
        <header className="planner-toolbar">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="editorial-title text-lg font-bold tracking-[0.1em] text-white sm:text-2xl">MAINTENANCE SCHEDULE PLANNER</h1>
          </div>
        </header>

        <div className="mt-3 flex justify-end">
          <button
            onClick={() => setPage((current) => current === "overview" ? "setup" : "overview")}
            className="rounded-xl border border-red-300 bg-red-600 px-5 py-3 text-base font-bold text-white shadow-lg shadow-red-950/35 transition hover:bg-red-400"
          >
            {page === "overview" ? "Build / update schedule" : "← Tracks overview"}
          </button>
        </div>

        {page === "overview" ? (
          <>
            <div aria-hidden="true" className="train-viewpoint" />

            <div className="mt-4 grid gap-3 xl:grid-cols-[1.08fr_0.92fr]">
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
            <PublicScheduleDownloads />
            <RecoveryOutcome run={run} />
            <RecoverySandbox
              run={run}
              capabilities={capabilities}
              busy={runBusy}
              onOpenDemo={openPublicDemo}
              onReplay={replayPublicDemo}
              onCreateDraft={createDisruptionDraft}
              onCreateSupplyDraft={createSupplyCsvDraft}
              onUpdateDraft={updateRecoveryDraft}
              onConfirmDraft={confirmRecoveryDraft}
            />
          </>
        ) : (
          <section className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr_0.8fr]" aria-label="Schedule setup">
            <div className="editorial-card c151-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">Build schedule</p>
              <h2 className="section-heading mt-1 text-xl font-bold text-white">Demand-book upload</h2>
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

            <div className="editorial-card c151-card rounded-2xl border border-red-400/25 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">Recovery</p>
              <h2 className="section-heading mt-1 text-xl font-bold text-white">Recovery sandbox</h2>
              <p className="mt-2 text-sm leading-6 text-slate-400">Scenario C recovery is available after a successful live C run. The public fixture remains a separate, fixed demonstration.</p>
              <button disabled={!capabilities?.public_demo_recovery.available || runBusy} onClick={() => void openPublicDemo()} className="mt-4 rounded-xl border border-red-300/40 bg-red-500/10 px-4 py-3 text-sm font-bold text-red-100 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500">Open public demo</button>
              <p className="mt-3 text-xs text-slate-500">{capabilities?.recovery.message ?? "Checking recovery capability…"}</p>
            </div>

            <div className="editorial-card c151-card rounded-2xl border border-slate-700/80 bg-slate-950/75 p-5 shadow-xl shadow-slate-950/40 backdrop-blur">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">Optimise</p>
              <h2 className="section-heading mt-1 text-xl font-bold text-white">Scenario control</h2>
              <p className="mt-2 text-sm leading-6 text-slate-400">Choose the objective before running a schedule refresh.</p>
              <div className="mt-4 grid grid-cols-3 gap-2">
                {(["A", "B", "C"] as Scenario[]).map((option) => {
                  const available = capabilities?.scenarios.find((item) => item.scenario === option)?.available ?? false;
                  return (
                  <button
                    key={option}
                    disabled={runBusy || !available}
                    onClick={() => setScenario(option)}
                    className={`rounded-lg border px-2 py-3 text-sm font-black transition disabled:cursor-not-allowed disabled:border-slate-800 disabled:bg-slate-900/50 disabled:text-slate-600 ${scenario === option ? "border-red-400 bg-red-500 text-white shadow-lg shadow-red-500/20" : "border-slate-700 bg-slate-900 text-slate-300 hover:border-red-500"}`}
                  >
                    {option}
                  </button>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-slate-500">A: strict supply · B: strict schedule · C: balanced</p>
              <button
                disabled={!scheduleInputReady || runBusy || !capabilities?.scenarios.find((item) => item.scenario === scenario)?.available}
                onClick={() => void startRun()}
                aria-busy={runBusy}
                className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-red-500 px-4 py-3 font-bold text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
              >
                {runBusy && <span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-white/35 border-t-white" />}
                {runBusy ? "Running schedule…" : "Run schedule"}
              </button>
              <p className="mt-3 text-xs leading-5 text-slate-400">{refreshNotice}</p>
            </div>
          </section>
        )}
      </section>
      <GroundedCopilot run={run} />
    </main>
  );
}
