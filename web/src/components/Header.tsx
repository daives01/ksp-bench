import type { ReactNode } from "react";

type HeaderProps = {
  children?: ReactNode;
};

export function Header({ children }: HeaderProps) {
  return (
    <header className="border-b border-border/80 bg-background/80">
      <div className="mx-auto flex w-full max-w-7xl flex-col px-4 pt-6 sm:px-6 lg:px-8">
        <div className="pb-6">
          <h1 className="font-display text-5xl font-black uppercase leading-none text-foreground sm:text-7xl">
            KSP BENCH
          </h1>
        </div>
        {children ? <div className="border-t border-border/80 py-3">{children}</div> : null}
      </div>
    </header>
  );
}
