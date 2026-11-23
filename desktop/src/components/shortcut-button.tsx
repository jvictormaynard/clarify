import { Pencil } from 'lucide-react';
import type { MouseEventHandler } from "react";
import { t } from '../i18n';
import { shortcutKeyName } from "../settings/display-labels";
import type { HotkeyDefinition } from '../settings/bridge';
import { Button } from './ui';
import '../styles/shortcut-button.css';

export function ShortcutButton({ shortcut, display, label, disabled, onClick }: {
  shortcut?: HotkeyDefinition | null; display?: string; label?: string; disabled?: boolean; onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  const keys = (shortcut ? [...shortcut.modifiers, shortcut.key] : (display || '').split('+').filter(Boolean)).map(shortcutKeyName);
  return <Button className="shortcut shortcut-control" aria-label={label || (keys.length ? keys.join("+") : t("Definir atalho"))} aria-description={keys.length ? keys.join("+") : t("Definir atalho")} disabled={disabled} onClick={onClick}>
    <span className="shortcut-keycaps" aria-hidden="true">{keys.length ? keys.map((key, index) => <kbd key={index}>
      {key.toLowerCase() === 'win' ? <><span className="sr-only">Win</span><svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M1 1h6v6H1zm8 0h6v6H9zM1 9h6v6H1zm8 0h6v6H9z" /></svg></> : key}
    </kbd>) : <span>{t('Definir atalho')}</span>}</span>
    <Pencil size={16} aria-hidden="true" />
  </Button>;
}
