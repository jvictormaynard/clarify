import { Menu as MenuPrimitive } from "@base-ui/react/menu";

import { cn } from "../../lib/utils";

const Menu = MenuPrimitive.Root;
const MenuTrigger = MenuPrimitive.Trigger;

function MenuPopup({ className, children, ...props }: MenuPrimitive.Popup.Props) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Positioner align="end" sideOffset={4} className="z-[130]" data-slot="menu-positioner">
        <MenuPrimitive.Popup
          className={cn(
            "dropdown-glass relative flex max-w-[calc(100vw-2rem)] min-w-[min(10rem,calc(100vw-2rem))] origin-(--transform-origin) rounded-lg text-foreground shadow-[0_16px_40px_-18px_rgb(0_0_0/55%)] outline-none focus:outline-none dark:shadow-[0_18px_44px_-18px_rgb(0_0_0/80%)] [-webkit-app-region:no-drag]",
            className,
          )}
          data-slot="menu-popup"
          {...props}
        >
          <div className="max-h-(--available-height) w-full overflow-y-auto p-1">{children}</div>
        </MenuPrimitive.Popup>
      </MenuPrimitive.Positioner>
    </MenuPrimitive.Portal>
  );
}

function MenuItem({ className, variant = "default", ...props }: MenuPrimitive.Item.Props & {
  variant?: "default" | "destructive";
}) {
  return (
    <MenuPrimitive.Item
      className={cn(
        "[&>svg]:-mx-0.5 flex min-h-8 cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1 text-base text-foreground outline-none data-disabled:pointer-events-none data-disabled:cursor-not-allowed data-highlighted:bg-accent data-[variant=destructive]:text-destructive-foreground data-highlighted:text-accent-foreground data-disabled:opacity-64 sm:min-h-7 sm:text-sm [&>svg:not([class*='opacity-'])]:opacity-80 [&>svg:not([class*='size-'])]:size-4.5 sm:[&>svg:not([class*='size-'])]:size-4 [&>svg:not([class*='text-'])]:text-muted-foreground data-[variant=destructive]:[&>svg:not([class*='text-'])]:text-current [&>svg]:pointer-events-none [&>svg]:shrink-0",
        className,
      )}
      data-slot="menu-item"
      data-variant={variant}
      {...props}
    />
  );
}

function MenuSeparator({ className, ...props }: MenuPrimitive.Separator.Props) {
  return <MenuPrimitive.Separator className={cn("mx-2 my-1 h-px bg-border", className)} data-slot="menu-separator" {...props} />;
}

export { Menu, MenuTrigger, MenuPopup, MenuItem, MenuSeparator };
