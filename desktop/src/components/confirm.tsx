import type { ReactNode } from "react";
import { Dialog, DialogDescription, DialogFooter, DialogHeader, DialogPopup, DialogTitle } from "./primitives/dialog";

export function Confirm({ open, title, description, children, onOpenChange, error }: {
  open: boolean;
  title: string;
  description: string;
  children: ReactNode;
  error?: ReactNode;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogPopup>
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
