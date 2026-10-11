import type { ReactNode } from "react";
import { Header } from "./header";
import { Sidebar } from "./sidebar";

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="app flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="main flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
