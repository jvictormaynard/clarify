import { useRef, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { Collapsible, CollapsiblePanel, CollapsibleTrigger } from "./primitives/collapsible";
import { cn } from "../lib/utils";

export function SettingsDisclosure({ title, children, className, defaultOpen, open, onOpenChange, keepMounted = true }: {
  title: string; children: ReactNode; className?: string; defaultOpen?: boolean;
  open?: boolean; onOpenChange?: (open: boolean) => void; keepMounted?: boolean;
}) {
  const initialOpen = useRef(defaultOpen);
  return <Collapsible className={cn("settings-disclosure", className)} defaultOpen={initialOpen.current} open={open} onOpenChange={onOpenChange}>
    <CollapsibleTrigger className="group flex min-h-10 w-full items-center gap-1.5 rounded-b-xl px-3 text-left text-xs font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring data-panel-open:rounded-none sm:px-4">
      <ChevronRight aria-hidden className="size-3.5 shrink-0 transition-transform duration-150 group-data-panel-open:rotate-90 motion-reduce:transition-none" />
      {title}
    </CollapsibleTrigger>
    <CollapsiblePanel keepMounted={keepMounted}>
      <div className="settings-disclosure-content border-t border-border/50 [&>*+*]:border-t [&>*+*]:border-border/50">
        {children}
      </div>
    </CollapsiblePanel>
  </Collapsible>;
}
