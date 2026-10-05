"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            aria-label="Toggle color theme"
            size="icon"
            variant="ghost"
            onClick={() =>
              setTheme(resolvedTheme === "dark" ? "light" : "dark")
            }
          />
        }
      >
        <Sun aria-hidden="true" className="dark:hidden" />
        <Moon aria-hidden="true" className="hidden dark:block" />
      </TooltipTrigger>
      <TooltipContent>Toggle color theme</TooltipContent>
    </Tooltip>
  );
}
