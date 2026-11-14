import { Badge } from "@/components/ui/badge";

export function RunStatus({ status }: { status: string }) {
  const tone =
    status === "COMPLETED"
      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : status === "FAILED"
        ? "bg-destructive/10 text-destructive"
        : "bg-amber-500/10 text-amber-700 dark:text-amber-300";
  return (
    <Badge className={tone} variant="secondary">
      {status.replaceAll("_", " ")}
    </Badge>
  );
}
