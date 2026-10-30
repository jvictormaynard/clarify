import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Row, Section } from "../components/ui";
import { actionDisplayName, hotkeyLabel } from "../settings/use-text-actions";

export function ShortcutsPage({ controller }: SettingsPageProps) {
  const { state, run, setCapture, setConfirmAction } = controller;
  return (
    <><Section title={t("Ações rápidas")}>
      {state.hotkeyActions.filter(item => !["rewrite_hotkey", "translation_hotkey"].includes(item.id)).map((item) => (
        <Row key={item.id} title={t(item.label)}>
          <div className="inline-actions">
            <Button
              type="button"
              className="shortcut"
              onClick={() => setCapture(item.id)}
            >
              {item.display || item.definition?.display || t("Definir atalho")}
            </Button>
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
        <Button className="shortcut" onClick={() => controller.textActions.open(action)}>{hotkeyLabel(action.shortcut) || t("Definir atalho")}</Button>
      </Row>)}
    </Section></>
  );
}
