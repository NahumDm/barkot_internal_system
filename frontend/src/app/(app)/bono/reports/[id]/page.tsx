import BonoReportDetailPage from "@/features/bono/bono-report-detail";

export default async function BonoReportPage({
  params,
}: Readonly<{ params: Promise<{ id: string }> }>) {
  const { id } = await params;
  return <BonoReportDetailPage reportId={Number(id)} />;
}
