import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Picker, Row, Section } from "../components/ui";

export function ShortcutsPage({ controller }: SettingsPageProps) {
  const { state, run, setCapture, setConfirmAction } = controller;
  return (
    <Section title="Ações rápidas">
      {state.hotkeyActions.map((item) => (
        <Row key={item.id} title={item.label}>
          <div className="inline-actions">
            <button
              type="button"
              className="control shortcut"
              onClick={() => setCapture(item.id)}
            >
              {item.display || item.definition?.display || "Definir atalho"}
            </button>
            <Button
              variant="ghost"
              aria-label={`Restaurar ${item.label}`}
              onClick={() => void run("resetHotkey", item.id)}
            >
              Restaurar
            </Button>
          </div>
        </Row>
      ))}
      <Button
        variant="text"
        onClick={() => setConfirmAction("resetAllHotkeys")}
      >
        Restaurar todos os atalhos
      </Button>
      <Row title="Modo de gravação">
        <Picker
          label="Modo de gravação"
          value={state.hotkeyActivationMode}
          options={[
            { id: "toggle", label: "Pressionar para iniciar e parar" },
            ...(state.hotkeyPushToTalkSupported
              ? [{ id: "push_to_talk", label: "Segurar para gravar" }]
              : []),
          ]}
          onChange={(v) => void run("setHotkeyActivationMode", v)}
        />
      </Row>
    </Section>
  );
}
