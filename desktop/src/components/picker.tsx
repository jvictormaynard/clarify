import { t } from "../i18n";
import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Command } from "cmdk";
import { Check, ChevronDown, Search, RefreshCw } from "lucide-react";
import type { Option } from "../settings/bridge";

export function Picker({
  label,
  value,
  options,
  onChange,
  onRefresh,
  busy,
  disabled,
  empty = t("Nenhuma opção disponível."),
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  onRefresh?: () => void;
  busy?: boolean;
  disabled?: boolean;
  empty?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        // Exit animations can keep cmdk mounted across a quick close/reopen.
        if (next) setSearch("");
        setOpen(next);
      }}
    >
      <Popover.Trigger
        className="control picker"
        role="combobox"
        aria-label={label}
        aria-expanded={open}
        disabled={disabled}
      >
        <span>
          {t(options.find((item) => item.id === value)?.label ||
            value ||
            "Selecionar…")}
        </span>
        <ChevronDown size={16} aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="popover"
          sideOffset={6}
          align="start"
          collisionPadding={12}
        >
          <Command label={t("Buscar {label}", { label: label.toLowerCase() })}>
            <div className="search">
              <Search size={16} aria-hidden />
              <Command.Input
                value={search}
                onValueChange={setSearch}
                aria-label={t("Buscar {label}", { label: label.toLowerCase() })}
                placeholder={t("Buscar {label}…", { label: label.toLowerCase() })}
              />
              {onRefresh && (
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t("Atualizar {label}", { label: label.toLowerCase() })}
                  onClick={onRefresh}
                  disabled={busy}
                >
                  <RefreshCw size={15} className={busy ? "spin" : ""} />
                </button>
              )}
            </div>
            <Command.List>
              <Command.Empty>{busy ? t("Carregando…") : empty}</Command.Empty>
              {options.map((item) => (
                <Command.Item
                  key={item.id}
                  value={item.id || "system-default"}
                  keywords={[item.label, t(item.label)]}
                  onSelect={() => {
                    onChange(item.id);
                    setOpen(false);
                  }}
                >
                  <span>{t(item.label)}</span>
                  <Check
                    size={16}
                    style={{ opacity: item.id === value ? 1 : 0 }}
                    aria-hidden
                  />
                </Command.Item>
              ))}
            </Command.List>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
