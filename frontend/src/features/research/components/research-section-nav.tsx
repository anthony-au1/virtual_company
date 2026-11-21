"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const sectionLinks = [
  { label: "Campaigns", href: "/research" },
  { label: "All Runs", href: "/research/runs" },
] as const;

export function ResearchSectionNav() {
  const pathname = usePathname();
  const runsSelected =
    pathname === "/research/runs" ||
    pathname.startsWith("/research/runs/") ||
    (pathname.startsWith("/research/") && pathname !== "/research/");
  const selectedHref = runsSelected ? "/research/runs" : "/research";

  return (
    <nav aria-label="Research sections" className="mb-6">
      <ul className="flex w-fit gap-1 border-b">
        {sectionLinks.map(({ label, href }) => {
          const selected = selectedHref === href;
          return (
            <li key={href}>
              <Link
                aria-current={selected ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-10 items-center border-b-2 px-3 text-sm font-medium transition-colors",
                  selected
                    ? "border-primary text-foreground"
                    : "text-muted-foreground hover:border-border hover:text-foreground border-transparent",
                )}
                href={href}
              >
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
