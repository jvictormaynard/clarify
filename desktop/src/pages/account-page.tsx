import { useState } from "react";
import { Button, Field, Row, Section, Toggle } from "../components/ui";
import type { SettingsPageProps } from "../settings/use-settings";
import { AccountSignIn } from "../components/account-sign-in";

export function AccountPage({ controller }: SettingsPageProps) {
  const { state, run, dirty } = controller;
  const account = state.accountState;
  const [server, setServer] = useState(account?.endpoint || "");
  const [deleting, setDeleting] = useState(false);
  const command = (action: string, value = "") => void run("accountCommand", action, value);
  if (!account) return null;
  const used = Math.ceil(((account.usage.used_ms || 0) + (account.usage.reserved_ms || 0)) / 60000);
  const limit = Math.floor((account.usage.limit_ms || 0) / 60000);
  return <>
    <p className="hint">A conta é opcional. Você pode continuar com sua chave ou com os modelos locais deste computador.</p>
    {account.error && <p role="alert" className="error">{account.error}</p>}
    {account.syncError && <p role="alert" className="error">{account.syncError}</p>}
    <fieldset disabled={account.busy || dirty}>
      {!account.signedIn ? <Section title="Entrar ou criar conta">
        {!account.endpoint && <p className="hint">O serviço ainda não está configurado nesta versão. Os modos locais e com chave própria continuam disponíveis.</p>}
        <AccountSignIn account={account} command={command} />
        <details><summary>Servidor próprio</summary>
          <Field title="Endereço do servidor" value={server} placeholder="https://…" onChange={e => setServer(e.target.value)} />
          <Button onClick={() => command("configure", server)}>Salvar servidor</Button>
        </details>
      </Section> : <>
        <Section title={account.email}>
          <Toggle title="Usar processamento do Clarify" checked={account.hosted}
            hint="Envia áudio e texto ao serviço Clarify e ao Groq. Com a opção desativada, o ditado usa seus modelos e chaves atuais."
            onChange={v => command("hosted", v ? "1" : "0")} />
          <Row title={`${used} de ${limit} minutos neste mês`} hint="Cota compartilhada entre desktop e iPhone. Processamento local e chave própria não usam esta cota.">
            <Button onClick={() => command("refresh")}>Atualizar consumo</Button>
          </Row>
          {account.usage.hosted_available === false && <p className="hint">O processamento gratuito está indisponível no momento.</p>}
        </Section>
        <Section title="Dicionário compartilhado">
          <p className="hint">Ao conectar, suas palavras são combinadas com as palavras da conta. As próximas alterações são sincronizadas ao salvar. Atalhos, chaves e histórico permanecem neste computador.</p>
          <Button onClick={() => command("sync")}>{account.syncEnabled ? "Sincronizar agora" : "Conectar dicionário"}</Button>
          {account.dictionaryConflict && <>
            <p className="hint">A escolha abaixo se aplica somente às palavras alteradas nos dois dispositivos. As outras alterações serão combinadas.</p>
            <Button onClick={() => command("sync-local")}>Manter as versões deste computador</Button>
            <Button onClick={() => command("sync-remote")}>Usar as versões da conta</Button>
          </>}
        </Section>
        <Section title="Sessão">
          <p className="hint">Ao sair, o Clarify volta ao dicionário e ao processamento locais. As palavras da conta ficam separadas por conta neste computador.</p>
          <Button onClick={() => command("logout")}>Sair da conta</Button>
          {!deleting ? <Button onClick={() => setDeleting(true)}>Excluir conta…</Button> : <>
            <p className="error">Excluir a conta remove seu dicionário compartilhado e o acesso ao serviço. Esta ação não pode ser desfeita. O histórico local será mantido.</p>
            <Button onClick={() => command("delete")}>Confirmar exclusão da conta</Button>
            <Button onClick={() => setDeleting(false)}>Cancelar</Button>
          </>}
        </Section>
      </>}
      {account.busy && <p role="status" className="hint">Aguarde…</p>}
    </fieldset>
  </>;
}
