"use client";

import { BriefcaseBusiness, Search, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Separator } from "@/components/ui/separator";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { cn } from "@/lib/utils";

const navigation = [
  { label: "Campaigns", icon: BriefcaseBusiness, href: "/campaigns" },
  { label: "Research", icon: Search, href: "/research" },
  { label: "Leads", icon: Users },
];

export function AppShell({ children }: React.PropsWithChildren) {
  const pathname = usePathname();
  return (
    <div className="grid min-h-screen grid-rows-[3.5rem_auto_1fr] md:grid-cols-[14rem_1fr] md:grid-rows-[3.5rem_1fr]">
      <header className="bg-background col-span-full flex items-center justify-between border-b px-4 md:px-5">
        <div className="flex items-center gap-2.5">
          <div
            aria-hidden="true"
            className="bg-primary text-primary-foreground flex size-7 items-center justify-center rounded-md"
          >
            <BriefcaseBusiness className="size-4" />
          </div>
          <span className="text-sm font-semibold tracking-tight">
            Virtual Consultancy
          </span>
        </div>
        <ThemeToggle />
      </header>

      <aside className="bg-sidebar border-b md:border-r md:border-b-0">
        <nav aria-label="Primary" className="p-2 md:p-3">
          <ul className="flex gap-1 overflow-x-auto md:flex-col">
            {navigation.map(({ label, icon: Icon, href }) => (
              <li key={label}>
                {href ? (
                  <Link
                    aria-current={
                      pathname.startsWith(href) ? "page" : undefined
                    }
                    className={cn(
                      "text-sidebar-foreground flex h-8 min-w-max items-center gap-2 rounded-md px-2.5 text-sm",
                      pathname.startsWith(href)
                        ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                        : "text-muted-foreground hover:bg-sidebar-accent/70",
                    )}
                    href={href}
                  >
                    <Icon aria-hidden="true" className="size-4" />
                    {label}
                  </Link>
                ) : (
                  <span
                    aria-disabled="true"
                    className={cn(
                      "text-sidebar-foreground flex h-8 min-w-max cursor-default items-center gap-2 rounded-md px-2.5 text-sm",
                      "text-muted-foreground",
                    )}
                  >
                    <Icon aria-hidden="true" className="size-4" />
                    {label}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </nav>
        <Separator className="hidden md:block" />
        <p className="text-muted-foreground hidden px-5 py-4 text-xs leading-relaxed md:block">
          Campaign setup, research runs, and human review.
        </p>
      </aside>

      <main className="min-w-0 p-4 sm:p-6 lg:p-8">{children}</main>
    </div>
  );
}
