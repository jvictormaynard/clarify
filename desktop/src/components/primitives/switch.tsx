import { Switch as SwitchPrimitive } from "@base-ui/react/switch";

import { cn } from "../../lib/utils";

function Switch({
  className,
  size = "default",
  mixed = false,
  ...props
}: SwitchPrimitive.Root.Props & { size?: "default" | "sm"; mixed?: boolean }) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "inline-flex h-[calc(var(--thumb-size)+2px)] w-[calc(var(--thumb-size)*2-2px)] shrink-0 cursor-pointer items-center rounded-full p-[2px] outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background data-checked:bg-primary data-unchecked:bg-input data-disabled:cursor-not-allowed data-disabled:opacity-50 data-[mixed]:bg-input",
        size === "sm"
          ? "[--thumb-size:--spacing(4)] sm:[--thumb-size:--spacing(3.5)]"
          : "[--thumb-size:--spacing(5)] sm:[--thumb-size:--spacing(4)]",
        className,
      )}
      data-size={size}
      data-slot="switch"
      data-mixed={mixed ? "" : undefined}
      // Base UI copies every key we pass, even `undefined`, over its own
      // aria-checked. Only pass the attribute when mixed so the real state
      // survives for screen readers.
      {...(mixed ? { "aria-checked": "mixed" as const } : {})}
      {...props}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          "pointer-events-none block size-[calc(var(--thumb-size)-2px)] shrink-0 rounded-(--thumb-size) bg-background shadow-sm/5 dark:data-unchecked:bg-muted-foreground data-checked:translate-x-[calc(var(--thumb-size)-4px)]",
          mixed &&
            "translate-x-[calc((var(--thumb-size)-4px)/2)] opacity-70 data-checked:translate-x-[calc((var(--thumb-size)-4px)/2)]",
        )}
        data-slot="switch-thumb"
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
