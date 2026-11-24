import { ShortcutButton } from "../components/shortcut-button";
import { electron } from "../platform";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Row, Section } from "../components/ui";
import { shortcutKeyName } from "../settings/display-labels";

export function ShortcutsPage({ controller }: SettingsPageProps) {
  const { state, run, setCapture, setConfirmAction } = controller;
  return (
    <Section title={t("Atalhos do aplicativo")}>
      {!!state.hotkeyUnavailable?.length && <p className="hint" role="status">
        {t("Atalhos indisponíveis ({v0})", {v0: state.hotkeyUnavailable.map(item => item.split("+").map(shortcutKeyName).join("+")).join(", ")})}
      </p>}
      {state.hotkeyActions.filter(item => !["rewrite_hotkey", "translation_hotkey"].includes(item.id)).map((item) => (
        <Row key={item.id} title={t(item.id === "toggle_visibility" && electron() ? "Expandir / recolher dock" : item.label)}>
          <div className="inline-actions">
            <ShortcutButton label={t(item.label)} display={item.display || item.definition?.display}
              onClick={event => setCapture(item.id, event.currentTarget)} />
            <Button
              variant="ghost"
              aria-label={t("Restaurar {name}", { name: item.label })}
              onClick={() => void run("resetHotkey", item.id)}
            >{t("Restaurar")}</Button>
          </div>
        </Row>
      ))}
      <Button
        variant="text"
        onClick={() => setConfirmAction("resetAllHotkeys")}
      >{t("Restaurar atalhos padrão")}</Button>
    </Section>
  );
}
