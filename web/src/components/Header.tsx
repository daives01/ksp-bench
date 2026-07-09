import type { ReactNode } from "react";
import { Orbit } from "lucide-react";

type HeaderProps = {
  actions?: ReactNode;
  children?: ReactNode;
};

export function Header({ actions, children }: HeaderProps) {
  return (
    <header className="bg-background/88 backdrop-blur-xl">
      <div className="mx-auto flex min-h-20 w-full max-w-[92rem] flex-col justify-center pl-4 pr-2 sm:pl-6 sm:pr-3 lg:pl-8 lg:pr-4">
        <div className="flex flex-col gap-4 py-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-3">
              <div className="relative grid h-11 w-11 shrink-0 place-items-center">
                <Orbit className="absolute h-10 w-10 rotate-12 text-primary" strokeWidth={1.35} />
                <Orbit className="absolute h-10 w-10 -rotate-45 text-primary/70" strokeWidth={1.05} />
                <span className="h-2.5 w-2.5 rounded-full bg-primary shadow-[0_0_20px_hsl(var(--primary))]" />
              </div>
              <h1 className="truncate font-display text-3xl font-black uppercase leading-none text-foreground sm:text-4xl">
                KSP Bench
              </h1>
            </div>
            {children ? <div className="pt-3">{children}</div> : null}
          </div>
          {actions ? <div className="shrink-0">{actions}</div> : null}
        </div>
      </div>
    </header>
  );
}
