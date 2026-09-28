export default function PagePlaceholder({ title }: { title: string }) {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink-secondary">
        Presentational shell for this module — functional implementation lands in later phases (UX
        §3, spec §7.4).
      </p>
    </section>
  );
}
