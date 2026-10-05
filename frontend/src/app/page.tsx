import { ArrowRight, CheckCircle2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function Home() {
  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-5xl">
      <div className="mb-6">
        <Badge variant="secondary">
          <CheckCircle2 aria-hidden="true" data-icon="inline-start" />
          Foundation ready
        </Badge>
        <h1
          id="page-title"
          className="mt-3 text-2xl font-semibold tracking-tight"
        >
          Virtual Consultancy
        </h1>
        <p className="text-muted-foreground mt-1 max-w-2xl text-sm leading-6">
          The frontend workspace is ready for campaign and research workflows.
        </p>
      </div>

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Product workspace</CardTitle>
          <CardDescription>
            This foundation provides the shared shell, design system, API
            transport, and test infrastructure for the next product iteration.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
            <ArrowRight aria-hidden="true" className="size-4" />
            Campaign and research interfaces are intentionally not included yet.
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
