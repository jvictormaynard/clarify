import { useRef, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { Collapsible, CollapsiblePanel, CollapsibleTrigger } from "./primitives/collapsible";

export function SettingsDisclosure({ title, children, defaultOpen }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const initialOpen = useRef(defaultOpen);
  return <Collapsible className="settings-disclosure" defaultOpen={initialOpen.current}>
    <CollapsibleTrigger className="group flex min-h-10 w-full items-center gap-1.5 rounded-b-xl px-3 text-left text-xs font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring data-panel-open:rounded-none sm:px-4">
      <ChevronRight aria-hidden className="size-3.5 shrink-0 transition-transform duration-150 group-data-panel-open:rotate-90 motion-reduce:transition-none" />
      {title}
    </CollapsibleTrigger>
    <CollapsiblePanel keepMounted>
      <div className="settings-disclosure-content border-t border-border/50 [&>*+*]:border-t [&>*+*]:border-border/50">
        {children}
      </div>
    </CollapsiblePanel>
  </Collapsible>;
}
