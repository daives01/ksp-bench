import { useEffect, useMemo, useState } from "react";
import { Github, Heart, X, CircleHelp } from "lucide-react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Header } from "@/components/Header";
import { ResultsView } from "@/components/ResultsView";
import { Button } from "@/components/ui/button";
import { loadBenchmarkData } from "@/lib/data";
import type { BenchmarkDataset } from "@/types";

export default function App() {
  const [dataset, setDataset] = useState<BenchmarkDataset | null>(null);
  const [isAboutOpen, setIsAboutOpen] = useState(false);
  useEffect(() => { void loadBenchmarkData().then(setDataset); }, []);
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsAboutOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);
  const runs = useMemo(() => dataset?.runs ?? [], [dataset]);
  if (!dataset) return <main className="flex min-h-screen items-center justify-center bg-background text-foreground"><div className="font-mono text-sm uppercase text-muted-foreground">Loading benchmark data</div></main>;
  return <div className="min-h-screen bg-background text-foreground">
    <div className="fixed inset-0 -z-10 launch-backdrop" />
    <Header actions={<div className="flex items-center gap-2">
      <Button variant="ghost" size="icon" className="header-link" onClick={() => setIsAboutOpen(true)} aria-label="About this benchmark">
        <CircleHelp className="h-4 w-4" />
      </Button>
      <Button asChild variant="ghost" size="icon" className="header-link"><a href="https://github.com/daives01/ksp-bench" target="_blank" rel="noreferrer" aria-label="View source"><Github className="h-4 w-4" /></a></Button>
      <Button asChild variant="ghost" size="icon" className="header-link"><a href="https://buymeacoffee.com/danielives" target="_blank" rel="noreferrer" aria-label="Support Daniel Ives"><Heart className="h-4 w-4" /></a></Button>
    </div>}><p className="mission-label">KERBIN / 80 KM · BENCHMARK v{dataset.benchmarkVersion}</p></Header>
    <Routes><Route path="/80km" element={<main className="mx-auto w-full max-w-[90rem] px-3 pb-12 pt-7 sm:px-4 lg:px-6"><ResultsView runs={runs} /></main>} /><Route path="*" element={<Navigate to="/80km" replace />} /></Routes>
    {isAboutOpen ? <div className="fixed inset-0 z-50 grid place-items-center bg-black/65 p-4" role="presentation" onMouseDown={() => setIsAboutOpen(false)}>
      <section className="w-full max-w-md rounded-lg border border-border bg-background p-6 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="about-benchmark-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <h2 id="about-benchmark-title" className="font-display text-2xl font-bold tracking-[-.04em] text-foreground">What is this?</h2>
          <Button variant="ghost" size="icon" className="-mr-2 -mt-2" onClick={() => setIsAboutOpen(false)} aria-label="Close"><X className="h-4 w-4" /></Button>
        </div>
        <p className="mt-4 text-sm leading-6 text-muted-foreground">KSP Bench compares how AI agents fly the same Kerbal Space Program launch. Each agent pilots a fixed rocket from Kerbin toward an 80 km orbit; the harness records the flight and scores whether it reaches a stable, controllable orbit. Use the results to compare mission performance, time, cost, and token use.</p>
        <p className="mt-3 font-mono text-xs uppercase text-muted-foreground">Benchmark v{dataset.benchmarkVersion}</p>
      </section>
    </div> : null}
  </div>;
}
