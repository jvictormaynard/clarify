import { t } from "../i18n";
import { useMemo, useState } from "react";
import { Check, RefreshCw } from "lucide-react";
import type { Option } from "../settings/bridge";
import { Button } from "./primitives/button";
import { SelectButton } from "./primitives/select";
import {
  useComboboxFilter, Combobox, ComboboxEmpty, ComboboxItem, ComboboxList,
  ComboboxPopup, ComboboxSearchInput, ComboboxTrigger,
} from "./primitives/combobox";

export function Picker({
  label, value, options, onChange, onRefresh, busy, disabled,
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
  const { contains } = useComboboxFilter();
  const filteredOptions = useMemo(
    () => options.filter(item => contains(t(item.label), search.trim())),
    [options, search, contains],
  );
  const selected = options.find(item => item.id === value) ?? null;
  const searchLabel = t("Buscar {label}", { label: label.toLocaleLowerCase() });

  return (
    <Combobox
      items={options}
      filteredItems={open ? filteredOptions : undefined}
      autoHighlight
      value={selected}
      itemToStringLabel={item => t(item.label)}
      itemToStringValue={item => item.id}
      isItemEqualToValue={(item, current) => item.id === current.id}
      open={open}
      disabled={disabled}
      inputValue={search}
      onInputValueChange={setSearch}
      onOpenChange={next => {
        if (next) setSearch("");
        setOpen(next);
      }}
      onValueChange={item => {
        if (item !== null) onChange(item.id);
      }}
    >
      <ComboboxTrigger
        role="combobox"
        aria-label={label}
        render={<SelectButton className="min-w-0" />}
      >
        {t(selected?.label || value || "Selecionar…")}
      </ComboboxTrigger>
      <ComboboxPopup>
        <div className={`relative shrink-0 ${onRefresh ? "pe-9" : ""}`}>
          <ComboboxSearchInput
            onKeyDown={event => {
              if (event.key !== "Enter" || event.nativeEvent.isComposing || event.keyCode === 229 ||
                  event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
                  event.currentTarget.hasAttribute("aria-activedescendant") || filteredOptions.length !== 1) return;
              // Pasted text can leave the single match without a virtual highlight.
              event.preventBaseUIHandler();
              event.preventDefault();
              onChange(filteredOptions[0]!.id);
              setOpen(false);
            }}
            aria-label={searchLabel}
            placeholder={t("Buscar {label}…", { label: label.toLocaleLowerCase() })}
          />
          {onRefresh && (
            <Button
              variant="ghost"
              size="icon-sm"
              className="absolute end-1 top-1.5"
              aria-label={t("Atualizar {label}", { label: label.toLocaleLowerCase() })}
              onClick={onRefresh}
              disabled={busy}
              aria-busy={busy || undefined}
            >
              <RefreshCw size={15} className={busy ? "spin" : undefined} aria-hidden />
            </Button>
          )}
        </div>
        <ComboboxEmpty>{busy ? t("Carregando…") : empty}</ComboboxEmpty>
        <ComboboxList>
          {(item: Option) => (
            <ComboboxItem key={item.id} value={item}>
              <span className="min-w-0 flex-1 truncate">{t(item.label)}</span>
              <Check size={16} className={item.id === value ? "opacity-100" : "opacity-0"} aria-hidden />
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxPopup>
    </Combobox>
  );
}
