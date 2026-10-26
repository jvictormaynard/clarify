import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Picker, Row, Section } from "../components/ui";

export function ShortcutsPage({ controller }: SettingsPageProps) {
  const { state, run, setCapture, setConfirmAction } = controller;
  return (
    <Section title={t("Ações rápidas")}>
      {state.hotkeyActions.map((item) => (
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
      >{t("Restaurar todos os atalhos")}</Button>
      <Row title={t("Modo de gravação")}>
        <Picker
          label={t("Modo de gravação")}
          value={state.hotkeyActivationMode}
          options={[
            { id: "toggle", label: t("Pressionar para iniciar e parar") },
            ...(state.hotkeyPushToTalkSupported
              ? [{ id: "push_to_talk", label: t("Segurar para gravar") }]
              : []),
          ]}
          onChange={(v) => void run("setHotkeyActivationMode", v)}
        />
      </Row>
    </Section>
  );
}
