import { useEffect, useMemo, useState } from "react";
import { Github, Heart } from "lucide-react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Header } from "@/components/Header";
import { ResultsView } from "@/components/ResultsView";
import { Button } from "@/components/ui/button";
import { loadBenchmarkData } from "@/lib/data";
import type { BenchmarkDataset } from "@/types";

export default function App() {
  const [dataset, setDataset] = useState<BenchmarkDataset | null>(null);
  useEffect(() => { void loadBenchmarkData().then(setDataset); }, []);
  const runs = useMemo(() => dataset?.runs ?? [], [dataset]);
  if (!dataset) return <main className="flex min-h-screen items-center justify-center bg-background text-foreground"><div className="font-mono text-sm uppercase text-muted-foreground">Loading benchmark data</div></main>;
  return <div className="min-h-screen bg-background text-foreground"><div className="fixed inset-0 -z-10 launch-backdrop" /><Header actions={<div className="flex items-center gap-2"><Button asChild variant="ghost" size="icon" className="header-link"><a href="https://github.com/daives01/ksp-bench" target="_blank" rel="noreferrer" aria-label="View source"><Github className="h-4 w-4" /></a></Button><Button asChild variant="ghost" size="icon" className="header-link"><a href="https://buymeacoffee.com/danielives" target="_blank" rel="noreferrer" aria-label="Support Daniel Ives"><Heart className="h-4 w-4" /></a></Button></div>}><p className="mission-label">KERBIN / 80 KM</p></Header><Routes><Route path="/80km" element={<main className="mx-auto w-full max-w-[78rem] px-4 pb-12 pt-7 sm:px-6 lg:px-8"><ResultsView runs={runs} /></main>} /><Route path="*" element={<Navigate to="/80km" replace />} /></Routes></div>;
}
