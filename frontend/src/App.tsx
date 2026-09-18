import { useEffect, useState } from "react";
import { railAccessApi } from "./api/client";
import type { Health, ValidationStatus } from "./api/types";

const capabilities = [
  ["Input intake", "Eight official CSVs", "Phase 1"],
  ["Schedule engine", "Constraint-safe allocation", "Phase 1–2"],
  ["Validator gate", "Organiser adapter", "Awaiting package"],
  ["Recovery sandbox", "Disruption re-planning", "Phase 4"]
];

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    railAccessApi
      .getHealth()
      .then((result) => {
        setHealth(result);
        setApiError(null);
      })
      .catch((error: Error) => {
        setHealth(null);
        setApiError(error.message);
      });
  }, []);

  const validatorStatus: ValidationStatus | "checking" = health?.validator_status ?? "checking";

  return (
    <main className="min-h-screen bg-[#07111f] px-6 py-8 text-slate-100 sm:px-10">
      <section className="mx-auto max-w-5xl">
        <div className="flex items-center gap-3 text-xs font-bold uppercase tracking-[0.24em] text-cyan-300">
          <span className="h-px w-9 bg-cyan-400" />
          RailAccess AI · Foundation
        </div>
        <div className="mt-10 grid gap-8 lg:grid-cols-[1.35fr_0.65fr]">
          <div>
            <p className="text-sm font-semibold uppercase tracking-widest text-slate-400">Night possession control room</p>
            <h1 className="mt-3 text-5xl font-black tracking-tight text-white sm:text-6xl">Prove the plan before the first train.</h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
              The foundation is online. RailAccess will import the official demand book, create a possession schedule, and present its evidence to the organiser validator.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <span className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-200">API {health?.api_version ?? "connecting"}</span>
              <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-4 py-2 text-sm font-semibold text-amber-100">Validator: {validatorStatus}</span>
            </div>
            {apiError && <p className="mt-4 text-sm text-rose-300">Integration API unavailable: {apiError}</p>}
          </div>
          <aside className="rounded-2xl border border-slate-700 bg-slate-900/70 p-6 shadow-2xl shadow-cyan-950/30">
            <p className="text-sm font-semibold text-cyan-200">Trust boundary</p>
            <p className="mt-3 leading-7 text-slate-300">
              Local checks can confirm file contracts only. No schedule will be called feasible until the organiser validator is installed and returns zero hard violations.
            </p>
          </aside>
        </div>

        <section className="mt-14 grid gap-3 md:grid-cols-2">
          {capabilities.map(([title, detail, phase]) => (
            <article key={title} className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="font-bold text-slate-100">{title}</h2>
                  <p className="mt-1 text-sm text-slate-400">{detail}</p>
                </div>
                <span className="whitespace-nowrap text-xs font-semibold text-slate-500">{phase}</span>
              </div>
            </article>
          ))}
        </section>
      </section>
    </main>
  );
}
