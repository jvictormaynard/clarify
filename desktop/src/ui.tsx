import { useId, useState, type ReactNode } from "react";
import * as Popover from "@radix-ui/react-popover";
import * as Switch from "@radix-ui/react-switch";
import * as Dialog from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import { Check, ChevronDown, Search, RefreshCw, X } from "lucide-react";
import type { Option } from "./bridge";

// Composable Radix + cmdk primitives, as used by shadcn/ui. Styling stays local.
export function Picker({ label, value, options, onChange, onRefresh, busy, disabled, empty = "Nenhuma opção disponível." }: {
  label: string; value: string; options: Option[]; onChange: (value: string) => void;
  onRefresh?: () => void; busy?: boolean; disabled?: boolean; empty?: string;
}) {
  const [open, setOpen] = useState(false);
  return <Popover.Root open={open} onOpenChange={setOpen}>
    <Popover.Trigger className="control picker" role="combobox" aria-label={label} aria-expanded={open} disabled={disabled}>
      <span>{options.find(item => item.id === value)?.label || value || "Selecionar…"}</span>
      <ChevronDown size={16} aria-hidden />
    </Popover.Trigger>
    <Popover.Portal><Popover.Content className="popover" sideOffset={6} align="start" collisionPadding={12}>
      <Command label={`Buscar ${label.toLowerCase()}`}>
        <div className="search"><Search size={16} aria-hidden /><Command.Input aria-label={`Buscar ${label.toLowerCase()}`} placeholder={`Buscar ${label.toLowerCase()}…`} />
          {onRefresh && <button className="icon-button" aria-label={`Atualizar ${label.toLowerCase()}`} onClick={onRefresh} disabled={busy}><RefreshCw size={15} className={busy ? "spin" : ""} /></button>}
        </div>
        <Command.List><Command.Empty>{busy ? "Carregando…" : empty}</Command.Empty>
          {options.map(item => <Command.Item key={item.id} value={item.id || "system-default"} keywords={[item.label]} onSelect={() => { onChange(item.id); setOpen(false); }}>
            <span>{item.label}</span><Check size={16} style={{ opacity: item.id === value ? 1 : 0 }} aria-hidden />
          </Command.Item>)}
        </Command.List>
      </Command>
    </Popover.Content></Popover.Portal>
  </Popover.Root>;
}

export function Row({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return <div className="row"><div className="row-label"><div>{title}</div>{hint && <p>{hint}</p>}</div><div className="row-control">{children}</div></div>;
}
export function Toggle({ title, hint, checked, onChange }: { title: string; hint?: string; checked: boolean; onChange: (value: boolean) => void }) {
  const id = useId();
  return <div className="row"><div className="row-label"><label htmlFor={id}>{title}</label>{hint && <p>{hint}</p>}</div>
    <Switch.Root id={id} className="switch" checked={checked} onCheckedChange={onChange}><Switch.Thumb className="switch-thumb" /></Switch.Root></div>;
}
export function Confirm({ open, title, description, children, onOpenChange }: { open: boolean; title: string; description: string; children: ReactNode; onOpenChange: (open: boolean) => void }) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal>
    <Dialog.Overlay className="dialog-overlay" />
    <Dialog.Content className="dialog"><Dialog.Title>{title}</Dialog.Title><Dialog.Description>{description}</Dialog.Description>
      <Dialog.Close className="icon-button dialog-close" aria-label="Fechar"><X size={18} /></Dialog.Close><div className="dialog-actions">{children}</div>
    </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
