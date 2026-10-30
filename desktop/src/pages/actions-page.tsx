import { MoreHorizontal, Plus, Copy, Trash2 } from "lucide-react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Section, Switch } from "../components/ui";
import { Menu, MenuTrigger, MenuPopup, MenuItem, MenuSeparator } from "../components/primitives/menu";
import { actionDisplayName, hotkeyLabel } from "../settings/use-text-actions";
import { profileName } from "../settings/use-text-profile-editor";

export function ActionsPage({ controller: c }: SettingsPageProps) {
  const actions = c.state.textActions ?? [];
  const busy = c.textActions.saving || c.textActions.refreshing || c.state.textActionMutation?.busy || c.state.textActionsBusy;
  return <>
    <div className="page-toolbar">
      <p className="page-description">{t("Reescreva, traduza ou transforme um texto com suas próprias instruções.")}</p>
      <Button disabled={busy} loading={c.textActions.refreshing || c.state.textActionRefresh?.busy} onClick={() => void c.textActions.refresh()}>{t("Atualizar ações")}</Button>
      <Button variant="primary" disabled={!c.state.textActionContext || busy}
        onClick={() => c.textActions.open()}><Plus size={16} />{t("Nova ação")}</Button>
    </div>
    {c.state.textActionsError && <p className="error" role="alert">{t(c.state.textActionsError)}</p>}
    <Section title={t("Minhas ações")}>
      {!actions.length && <p className="hint">{c.state.textActionsBusy ? t("Carregando…") : t("Crie uma ação para usar suas instruções em outros aplicativos.")}</p>}
      {actions.map(action => {
        const profile = c.state.textActionProfiles?.find(profile => profile.id === action.processingProfileId);
        const shortcut = hotkeyLabel(action.shortcut);
        return <div className="text-action-row" key={action.id} id={`text-action-${action.id}`}>
          <div className="text-action-summary">
            <h3>{actionDisplayName(action)}</h3>
            <p>{action.kind === "translation" ? t("Tradução com escolha de idioma") : action.kind === "rewrite" ? t("Reescrita de texto") : t("Instruções personalizadas")}
              {profile && <> · {profile.managed ? t("Conta Clarify") : profileName(profile.id)}</>}</p>
            {shortcut && <kbd>{shortcut}</kbd>}
          </div>
          <div className="text-action-controls">
            <Switch label={t("Ativar {name}", { name: actionDisplayName(action) })} checked={action.enabled}
              disabled={busy} onChange={enabled => void c.textActions.toggle(action, enabled)} />
            <Button disabled={busy} onClick={() => c.textActions.open(action)}>{t("Editar ação")}</Button>
            <Menu><MenuTrigger aria-label={t("Mais opções de {name}", { name: actionDisplayName(action) })}
              disabled={busy}
              render={<Button variant="ghost" />}><MoreHorizontal size={16} /></MenuTrigger>
              <MenuPopup><MenuItem onClick={() => c.textActions.open(action, true)}><Copy />{t("Duplicar")}</MenuItem>
                <MenuSeparator /><MenuItem variant="destructive" onClick={() => c.textActions.requestDelete(action)}><Trash2 />{t("Excluir")}</MenuItem>
              </MenuPopup>
            </Menu>
          </div>
        </div>;
      })}
    </Section>
  </>;
}
