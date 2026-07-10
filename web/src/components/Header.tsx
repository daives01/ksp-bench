import type { ReactNode } from "react";
import { Orbit } from "lucide-react";

type HeaderProps = {
  actions?: ReactNode;
  children?: ReactNode;
};

export function Header({ actions, children }: HeaderProps) {
  return (
    <header className="site-header">
      <div className="mx-auto flex min-h-16 w-full max-w-[78rem] flex-col justify-center px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between gap-4 py-3">
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-3">
              <div className="relative grid h-8 w-8 shrink-0 place-items-center">
                <Orbit className="absolute h-8 w-8 rotate-12 text-primary" strokeWidth={1.5} />
                <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              </div>
              <h1 className="truncate font-display text-xl font-bold uppercase tracking-[-.06em] text-foreground sm:text-2xl">
                KSP Bench
              </h1>
            </div>
            {children ? <div className="pl-11 pt-0.5">{children}</div> : null}
          </div>
          {actions ? <div className="shrink-0">{actions}</div> : null}
        </div>
      </div>
    </header>
  );
}
