import { ShortcutButton } from "../components/shortcut-button";
import { useState } from "react";
import { LibraryPageHeader, LibraryToolbar } from "../components/library-page-layout";
import { MoreHorizontal, Plus, Copy, Trash2 } from "lucide-react";
import { t } from "../i18n";
import type { SettingsPageProps } from "../settings/use-settings";
import { Button, Section } from "../components/ui";
import { Menu, MenuTrigger, MenuPopup, MenuItem, MenuSeparator } from "../components/primitives/menu";
import { actionDisplayName } from "../settings/display-labels";

export function ActionsPage({ controller: c }: SettingsPageProps) {
  const [query, setQuery] = useState("");
  const actions = c.state.textActions ?? [];
  const visible = actions.filter(action => `${actionDisplayName(action)} ${action.prompt}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const busy = c.textActions.saving || c.textActions.refreshing || c.state.textActionMutation?.busy || c.state.textActionsBusy;
  return <section className="library-page">
    <LibraryPageHeader kind="actions" title={t("Ações")}>
      <Button variant="primary" disabled={!c.state.textActionContext || busy}
        onClick={() => c.textActions.open()}><Plus size={16} />{t("Nova ação")}</Button>
    </LibraryPageHeader>
    <LibraryToolbar label={t("Buscar ações")} query={query} onQueryChange={setQuery}
      refreshLabel={t("Atualizar ações")} busy={busy} onRefresh={() => c.textActions.refresh()} />

    {c.state.textActionsError && <p className="error" role="alert">{t(c.state.textActionsError)}</p>}
    <Section title={t("Minhas ações")} className="action-catalog">
      {!actions.length && <p className="hint">{c.state.textActionsBusy ? t("Carregando…") : t("Crie uma ação para usar suas instruções em outros aplicativos.")}</p>}
      {actions.length > 0 && !visible.length && <p className="hint">{t("Nenhum resultado encontrado.")}</p>}
      {visible.map(action => {
        return <div className="text-action-row" key={action.id} id={`text-action-${action.id}`}>
          <div className="text-action-summary">
            <h3 aria-label={actionDisplayName(action)}><Button variant="ghost" className="action-launch h-auto sm:h-auto max-w-full justify-start whitespace-normal px-2 py-1 text-left" disabled={!c.state.textActionContext || busy}
              aria-label={`${t("Usar ação")}: ${actionDisplayName(action)}`} onClick={() => c.textActions.use(action)}>{actionDisplayName(action)}</Button></h3>
            {!action.enabled && <span className="hint">{t("Desativada")}</span>}
          </div>
          <div className="text-action-controls">
            <ShortcutButton shortcut={action.shortcut} label={t("Editar ação")} disabled={busy} onClick={() => c.textActions.open(action)} />
            <Menu><MenuTrigger aria-label={t("Mais opções de {name}", { name: actionDisplayName(action) })}
              disabled={busy}
              render={<Button variant="ghost" />}><MoreHorizontal size={16} /></MenuTrigger>
              <MenuPopup><MenuItem onClick={() => void c.textActions.toggle(action, !action.enabled)}>{t(action.enabled ? "Desativar ação" : "Ativar ação")}</MenuItem><MenuItem onClick={() => c.textActions.open(action, true)}><Copy />{t("Duplicar")}</MenuItem>
                <MenuSeparator /><MenuItem variant="destructive" onClick={() => c.textActions.requestDelete(action)}><Trash2 />{t("Excluir")}</MenuItem>
              </MenuPopup>
            </Menu>
          </div>
        </div>;
      })}
    </Section>
  </section>;
}
