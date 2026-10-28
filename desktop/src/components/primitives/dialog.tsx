import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { XIcon } from "lucide-react";
import { type ComponentProps, createContext, type ReactNode, use, useState } from "react";
import { cn } from "../../lib/utils";
import { t } from "../../i18n";
import { Button } from "./button";
import { DIALOG_BACKDROP_CLASS, DIALOG_MOBILE_SHEET_CLASS, DIALOG_POPUP_CLASS } from "./dialog-styles";

const ControlledOpenContext = createContext<boolean | undefined>(undefined);

function RetainedWhileClosed({ open, children, ...props }: ComponentProps<"div"> & { open: boolean; children?: ReactNode }) {
  const controlledOpen = use(ControlledOpenContext);
  const isOpen = open && controlledOpen !== false;
  const [retained, setRetained] = useState(children);
  if (isOpen && retained !== children) {
    setRetained(children);
  }
  return <div {...props} inert={props.inert || !isOpen}>{isOpen ? children : retained}</div>;
}

function renderRetainedPopup(props: ComponentProps<"div">, state: { open: boolean }) {
  return <RetainedWhileClosed {...props} open={state.open} />;
}

function Dialog<Payload>(props: DialogPrimitive.Root.Props<Payload>) {
  return (
    <ControlledOpenContext value={props.open}>
      <DialogPrimitive.Root {...props} />
    </ControlledOpenContext>
  );
}

const DialogPortal = DialogPrimitive.Portal;

function DialogClose(props: DialogPrimitive.Close.Props) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

function DialogBackdrop({ className, ...props }: DialogPrimitive.Backdrop.Props) {
  return <DialogPrimitive.Backdrop forceRender className={cn(DIALOG_BACKDROP_CLASS, className)} data-slot="dialog-backdrop" {...props} />;
}

function DialogViewport({ className, ...props }: DialogPrimitive.Viewport.Props) {
  return (
    <DialogPrimitive.Viewport
      className={cn(
        "fixed inset-0 z-50 grid grid-rows-[1fr_auto_1fr] justify-items-center p-4",
        className,
      )}
      data-slot="dialog-viewport"
      {...props}
    />
  );
}

function DialogPopup({ className, children, showCloseButton = true, bottomStickOnMobile = true, ...props }: DialogPrimitive.Popup.Props & { showCloseButton?: boolean; bottomStickOnMobile?: boolean }) {
  return (
    <DialogPortal>
      <DialogBackdrop />
      <DialogViewport className={bottomStickOnMobile ? "max-sm:grid-rows-[1fr_auto] max-sm:p-0 max-sm:pt-12" : undefined}>
        <DialogPrimitive.Popup
          className={cn(DIALOG_POPUP_CLASS, "row-start-2 max-h-full max-w-lg text-popover-foreground", bottomStickOnMobile && DIALOG_MOBILE_SHEET_CLASS, className)}
          data-slot="dialog-popup"
          render={renderRetainedPopup}
          {...props}
        >
          {children}
          {showCloseButton && (
            <DialogPrimitive.Close aria-label={t("Fechar")} className="absolute end-2 top-2" render={<Button size="icon" variant="ghost" />}>
              <XIcon />
            </DialogPrimitive.Close>
          )}
        </DialogPrimitive.Popup>
      </DialogViewport>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 p-6 pe-12 max-sm:pb-4",
        className,
      )}
      data-slot="dialog-header"
      {...props}
    />
  );
}

function DialogFooter({
  className,
  variant = "default",
  ...props
}: ComponentProps<"div"> & {
  variant?: "default" | "bare";
}) {
  return (
    <div
      className={cn(
        "flex flex-col-reverse gap-2 px-6 sm:flex-row sm:justify-end sm:rounded-b-[calc(var(--radius-2xl)-1px)]",
        variant === "default" && "border-t bg-muted/72 py-4",
        variant === "bare" && "py-4",
        className,
      )}
      data-slot="dialog-footer"
      {...props}
    />
  );
}

function DialogTitle({ className, ...props }: DialogPrimitive.Title.Props) {
  return (
    <DialogPrimitive.Title
      className={cn("wrap-anywhere font-semibold text-xl leading-none", className)}
      data-slot="dialog-title"
      {...props}
    />
  );
}

function DialogDescription({ className, ...props }: DialogPrimitive.Description.Props) {
  return (
    <DialogPrimitive.Description
      className={cn("text-muted-foreground text-sm", className)}
      data-slot="dialog-description"
      {...props}
    />
  );
}

export { Dialog, DialogClose, DialogPopup, DialogHeader, DialogFooter, DialogTitle, DialogDescription };
