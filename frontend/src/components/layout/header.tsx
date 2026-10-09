export function Header() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-6">
      <p className="flex items-center gap-2.5 text-sm font-medium text-ink">
        <span aria-hidden="true" className="inline-block h-3.5 w-1 rounded-full bg-brand" />
        Barkot Bar &amp; Restaurant
      </p>
      <p className="text-xs text-ink-secondary">Internal operations</p>
    </header>
  );
}