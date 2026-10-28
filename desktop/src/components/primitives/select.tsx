import { mergeProps } from "@base-ui/react/merge-props";
import { useRender } from "@base-ui/react/use-render";
import { cva, type VariantProps } from "class-variance-authority";
import { ChevronDownIcon } from "lucide-react";

import { cn } from "../../lib/utils";

const selectTriggerVariants = cva(
  "relative inline-flex w-full min-w-36 cursor-pointer select-none items-center justify-between gap-2 rounded-lg border border-input bg-background not-dark:bg-clip-padding text-left text-base text-foreground shadow-xs/5 outline-none ring-ring/24 transition-[color,box-shadow,background-color] before:pointer-events-none before:absolute before:inset-0 before:rounded-[calc(var(--radius-lg)-1px)] not-data-disabled:not-focus-visible:not-aria-invalid:not-data-pressed:before:shadow-[0_1px_--theme(--color-black/4%)] pointer-coarse:after:absolute pointer-coarse:after:size-full pointer-coarse:after:min-h-11 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-inset aria-invalid:border-destructive/36 focus-visible:aria-invalid:border-destructive/64 focus-visible:aria-invalid:ring-destructive/16 disabled:pointer-events-none disabled:opacity-64 data-disabled:pointer-events-none data-disabled:opacity-64 sm:text-sm dark:bg-input/32 dark:aria-invalid:ring-destructive/24 dark:not-data-disabled:not-focus-visible:not-aria-invalid:not-data-pressed:before:shadow-[0_-1px_--theme(--color-white/6%)] [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4.5 sm:[&_svg:not([class*='size-'])]:size-4 [&_svg:not([class*='opacity-'])]:opacity-80 [&_svg:not([class*='text-'])]:text-icon-muted [[data-disabled],:focus-visible,[aria-invalid],[data-pressed]]:shadow-none",
  {
    defaultVariants: { size: "default" },
    variants: {
      size: {
        compact: "h-7 gap-1 rounded-md px-[calc(--spacing(2)-1px)] text-xs before:rounded-[calc(var(--radius-md)-1px)] [&_svg:not([class*='size-'])]:size-3.5",
        default: "min-h-9 px-[calc(--spacing(3)-1px)] sm:min-h-8",
        lg: "min-h-10 px-[calc(--spacing(3)-1px)] sm:min-h-9",
        sm: "min-h-8 gap-1.5 px-[calc(--spacing(2.5)-1px)] sm:min-h-7",
        xs: "h-7 gap-1 rounded-md px-[calc(--spacing(2)-1px)] text-sm before:rounded-[calc(var(--radius-md)-1px)] sm:h-6 sm:text-xs [&_svg:not([class*='size-'])]:size-4 sm:[&_svg:not([class*='size-'])]:size-3.5",
      },
    },
  },
);

function SelectButton({
  className,
  size = "default",
  children,
  render,
  ...props
}: useRender.ComponentProps<"button"> & VariantProps<typeof selectTriggerVariants>) {
  const defaultProps = {
    className: cn(selectTriggerVariants({ size }), className),
    "data-slot": "select-trigger",
    type: render ? undefined : ("button" as const),
  };
  return useRender({
    defaultTagName: "button",
    props: {
      ...mergeProps<"button">(defaultProps, props),
      children: (
        <>
          <span className="min-w-0 flex-1 truncate text-left">{children}</span>
          <ChevronDownIcon aria-hidden className="-me-1 size-3.5 shrink-0 opacity-70" />
        </>
      ),
    },
    render,
  });
}

export { SelectButton };
