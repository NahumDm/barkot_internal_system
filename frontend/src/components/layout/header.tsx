import { AccountMenu } from "./account-menu";

export function Header() {
  return (
    <header className="topbar flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-6">
      <p className="topbar-text text-sm text-ink-secondary">Barkot Bar &amp; Restaurant</p>
      <AccountMenu />
    </header>
  );
}
