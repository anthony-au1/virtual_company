import { Badge } from "@/components/ui/badge";

export function CampaignStatusBadge({ status }: { status: string }) {
  const style =
    status === "COMPLETED"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "FAILED"
        ? "bg-destructive/10 text-destructive"
        : status === "RUNNING"
          ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
          : "";
  return (
    <Badge className={style} variant="secondary">
      {status}
    </Badge>
  );
}
