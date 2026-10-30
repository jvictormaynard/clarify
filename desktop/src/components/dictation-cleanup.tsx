import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import type { DictationCleanupLevel } from "../settings/bridge";
import { Button, Picker, Row, Section } from "./ui";

export function DictationCleanup({ controller }: SettingsPageProps) {
  const { state, run } = controller;
  const level = state.dictationCleanupLevel ?? "";
  const help = {
    "": "Mantém as opções atuais de revisão até você escolher um nível.",
    preserve: "Mantém as palavras reconhecidas, sem revisão por IA. Dicionário e snippets continuam ativos.",
    light: "Ajusta apenas espaços e tabulações. Mantém hesitações, repetições e autocorreções.",
    clarity: "Usa a revisão configurada para melhorar a clareza. Se ela falhar, mantém a transcrição com os snippets.",
  }[level];
  return (
    <Section title={t("Revisão do ditado")}>
      <Row title={t("Nível de revisão")}>
        <Picker
          label={t("Nível de revisão")}
          value={level}
          options={[
            { id: "", label: t("Padrão atual") },
            { id: "preserve", label: t("Preservar palavras") },
            { id: "light", label: t("Ajustes mínimos") },
            { id: "clarity", label: t("Revisar clareza") },
          ]}
          onChange={(value) => void run("setDictationCleanupLevel", value as DictationCleanupLevel | "")}
        />
      </Row>
      <p className="hint">{t(help)}</p>
      {level === "preserve" && <p className="hint">{t("Exemplo: ‘Talvez terça, quer dizer, sexta.’ mantém todas as palavras.")}</p>}
      {level === "light" && <p className="hint whitespace-pre-wrap">{t("Exemplo: ‘Não  envie 42.’ vira ‘Não envie 42.’ Só os espaços mudam.")}</p>}
      {level === "clarity" && <p className="hint">{t("Exemplo possível: ‘O prazo, o prazo termina amanhã.’ vira ‘O prazo termina amanhã.’")}</p>}
      {level === "clarity" && state.dictationCleanupRefinementAllowed === false && (
        <div>
          <p className="hint" role="status">{t("Revisão indisponível nesta rota. As palavras serão preservadas.")}</p>
          {!(state.accountState?.managed || state.accountState?.signedIn) && <Button variant="text" onClick={() => void controller.navigate("style", state.textActionDictationContext === "local_asr" ? "local_asr_refinement" : "refinement")}>{t("Configurar revisão")}</Button>}
        </div>
      )}
      <p className="hint">{t("Snippets isolados inserem o texto salvo exatamente. Outros snippets são expandidos uma vez antes da revisão.")}</p>
    </Section>
  );
}
