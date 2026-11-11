import { ShortcutButton } from "../components/shortcut-button";
import { electron } from "../platform";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Row, Section } from "../components/ui";
import { actionDisplayName } from "../settings/display-labels";

export function ShortcutsPage({ controller }: SettingsPageProps) {
  const { state, run, setCapture, setConfirmAction } = controller;
  return (
    <><Section title={t("Ações rápidas")}>
      {state.hotkeyActions.filter(item => !["rewrite_hotkey", "translation_hotkey"].includes(item.id)).map((item) => (
        <Row key={item.id} title={t(item.id === "toggle_visibility" && electron() ? "Expandir / recolher dock" : item.label)}>
          <div className="inline-actions">
            <ShortcutButton label={t(item.label)} display={item.display || item.definition?.display}
              onClick={() => setCapture(item.id)} />
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
    <Section title={t("Atalhos das ações")}>
      <p className="hint">{t("Edite o atalho junto com as instruções da ação. A mudança só vale após salvar.")}</p>
      {(state.textActions ?? []).map(action => <Row key={action.id} title={actionDisplayName(action)}>
        <ShortcutButton label={`${t("Atalho")}: ${actionDisplayName(action)}`} shortcut={action.shortcut} onClick={() => controller.textActions.open(action)} />
      </Row>)}
    </Section></>
  );
}
