import { cn } from "@/lib/utils";

type MetricTileProps = {
  label: string;
  value: string;
  detail?: string;
  tone?: "green" | "amber" | "blue" | "neutral";
};

const toneClass = {
  green: "text-emerald-200",
  amber: "text-amber-200",
  blue: "text-sky-200",
  neutral: "text-foreground",
};

export function MetricTile({ label, value, detail, tone = "neutral" }: MetricTileProps) {
  return (
    <div className="rounded-md border border-border bg-card/80 p-4 shadow-glow">
      <div className="font-mono text-[11px] uppercase text-muted-foreground">{label}</div>
      <div className={cn("mt-2 font-display text-3xl font-bold leading-none", toneClass[tone])}>
        {value}
      </div>
      {detail ? <div className="mt-2 text-xs text-muted-foreground">{detail}</div> : null}
    </div>
  );
}
