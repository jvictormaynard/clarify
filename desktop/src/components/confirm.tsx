import type { ReactNode, RefObject } from "react";
import { Dialog, DialogDescription, DialogFooter, DialogHeader, DialogPopup, DialogTitle } from "./primitives/dialog";

export function Confirm({ open, title, description, children, onOpenChange, error, finalFocus }: {
  open: boolean;
  title: string;
  description: string;
  children: ReactNode;
  error?: ReactNode;
  finalFocus?: RefObject<HTMLElement | null>;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPopup finalFocus={finalFocus}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {error && <p role="alert" className="error px-6 pb-4">{error}</p>}
        <DialogFooter>{children}</DialogFooter>
      </DialogPopup>
    </Dialog>
  );
}
