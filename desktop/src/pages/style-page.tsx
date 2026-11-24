import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import type { WritingStyle } from "../settings/bridge";
import { writingStyleOptions } from "../settings/writing-style-options";
import { Picker, Row, Section } from "../components/ui";
import { dictationOutputEditingAllowed, textActionLanguages, TextEditing } from "../components/after-dictation-action";

export function StylePage({ controller: c }: SettingsPageProps) {
  const editingAllowed = dictationOutputEditingAllowed(c.state);
  return <Section>
    <TextEditing
      key={JSON.stringify([c.state.textActionContext, c.state.textActionDictationContext, c.state.afterDictationActionPaused])}
      controller={c}
    />
    {editingAllowed && <Row title={t("Tom")}>
      <Picker label={t("Tom")} value={c.state.dictationWritingStyle ?? ""} options={writingStyleOptions(c.state.dictationWritingStyle ?? "")}
        onChange={value => void c.run("setDictationWritingStyle", value as WritingStyle | "")} />
    </Row>}
    <Row title={t("Idioma de saída")}>
      <Picker label={t("Idioma de saída")} value={c.state.language}
        options={[{ id: "auto", label: t("Manter idioma de origem") }, ...textActionLanguages]}
        onChange={value => void c.run("setLanguage", value)} />
    </Row>
    {c.state.language !== "auto" && !editingAllowed &&
      <p className="hint" role="status">{t("O idioma fica salvo. Sem revisão, o ditado não é traduzido.")}</p>}
  </Section>;
}
