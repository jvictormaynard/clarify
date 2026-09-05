<p align="center">
  <img src="../assets/branding/clarify-logo.png" alt="Logo do Clarify" width="112">
</p>

# Clarify

[English](../README.md) · [Instalação](#instalação-no-windows) ·
[Como contribuir](../CONTRIBUTING.md) · [Segurança](../SECURITY.md)

O Clarify é um assistente desktop leve que transforma voz em texto bem
escrito dentro de qualquer aplicativo do Windows. Ele também reescreve e traduz
textos selecionados usando Gemini, OpenAI, Groq ou endpoints compatíveis.

## Principais recursos

- Transcrição e refinamento de voz com atalhos globais
- Reescrita segura de texto selecionado com verificação de foco
- Tradução de texto selecionado
- Integração nativa com atalhos e bandeja do Windows
- Interface em inglês, português, espanhol, alemão e russo
- Páginas de Settings separadas para gravação, speech-to-text, processamento de
  texto e integrações
- Estatísticas locais sem armazenar o conteúdo das transcrições
- Sem conta Clarify, backend próprio ou telemetria

> [!IMPORTANT]
> A transcrição ou o refinamento em provedores cloud exige uma chave de API. O
> Local Whisper pode transcrever sem chave e baixa seus assets somente após uma
> ação explícita. As chaves e estatísticas ficam no seu computador. O áudio e o
> texto selecionado são enviados diretamente ao provedor configurado.

## Instalação no Windows

### Instalador Windows (em preparação)

O repositório já contém o contrato fail-closed do MSI e da atualização
autenticada, mas o recurso não deve ser publicado ou considerado pronto antes
dos gates de assinatura gerenciada, armazenamento seguro de credenciais,
proveniência e validação manual. Quando uma release futura incluir o arquivo
`Clarify-windows-x64.msi`, instale somente se o publisher Authenticode e o
SHA-256 corresponderem à release. Consulte [segurança da distribuição e das
atualizações](windows-distribution.md) para os comportamentos de instalação,
upgrade, reparo, rollback e desinstalação.

### Release portátil comunitária

O projeto também publica uma release comunitária sem custo para o aplicativo
portátil. Ela contém `Clarify.exe`, seu arquivo SHA-256, o SBOM de runtime,
um arquivo ZIP e o código-fonte verificado do SoX. Ela não possui assinatura
Authenticode enquanto não houver patrocínio para a assinatura paga. O
SmartScreen pode pedir confirmação no primeiro uso. Essa release não inclui o
MSI nem o manifesto de atualização autenticado.

### Executável portátil

1. Abra a [versão mais recente](https://github.com/jvictormaynard/clarify/releases/latest).
2. Baixe `Clarify.exe` e salve-o em uma pasta sob seu controle.
3. Abra o executável.
4. Abra **Settings → Integrations** e escolha um caminho de configuração:
   - **Cloud:** selecione Gemini, OpenAI, Groq ou um endpoint compatível,
     informe a chave de API e valide o provedor.
   - **Local Whisper:** revise os requisitos e use **Download local ASR**. A
     transcrição local não exige chave. O refinamento cloud é opcional e pode
     ser ativado com **Allow cloud refinement**.
5. Abra **Settings → Speech-to-text** ou **Settings → Text processing** para
   escolher a rota de cada workflow. Cada rota pode ter seu próprio provedor,
   modelo, endpoint, estado e prompt.

Os executáveis portáteis comunitários não possuem assinatura de código. Confira
o arquivo SHA-256 publicado com a release antes de executar o download. O MSI e
o caminho de atualização no aplicativo permanecem desativados até que os gates
da release assinada sejam concluídos.

Se ainda não houver uma release, instale pelo código-fonte:

```powershell
git clone https://github.com/jvictormaynard/clarify.git
cd clarify
.\start.bat
```

É necessário ter Windows 10 ou 11, Python 3.11 ou mais recente e um microfone.
Na primeira execução, o script cria um ambiente virtual e instala as
dependências automaticamente.

## Atalhos

| Atalho | Ação |
| --- | --- |
| `Alt + L` | Iniciar ou encerrar a gravação |
| `Esc` | Cancelar a gravação ativa |
| `Alt + K` | Reescrever o texto selecionado |
| `Alt + T` | Traduzir o texto selecionado |
| `Alt + R` | Mostrar ou esconder o Clarify |

Os quatro atalhos globais podem ser capturados, validados e redefinidos em
**Settings → Shortcuts**. Depois de concluir uma gravação, o resultado aparece
diretamente e os atalhos continuam disponíveis sem clicar em **Dismiss**.

## Provedores e rotas de workflow

Um **provider** é o serviço e suas credenciais. Uma **route** define como cada
workflow usa esse serviço: provedor, modelo, endpoint, ativação e prompt. Os
providers são configurados em **Settings → Integrations**; as rotas ficam em
**Settings → Speech-to-text** e **Settings → Text processing**. O Local Whisper
usa um sidecar local e não exige chave para transcrição.

## Privacidade

O Clarify não possui servidor próprio. As configurações e estatísticas
locais ficam em `%APPDATA%\Clarify`. No Windows, as chaves ficam separadas
em `secrets.dpapi.json`, criptografadas pela DPAPI para o usuário atual. Chaves
antigas em texto simples são migradas e só são removidas de `config.json` depois
da confirmação da cópia protegida. Variáveis de ambiente são substituições
temporárias e não são persistidas.

Excluir somente o executável não apaga os dados. Para remover também as
credenciais, exclua `secrets.dpapi.json` ou toda a pasta de dados do
Clarify. Em execuções experimentais no Linux/macOS, `secrets.json` é um
fallback em texto simples com permissões restritas; não compartilhe esse arquivo.

## Desenvolvimento e contribuição

A documentação técnica principal está em inglês para facilitar a colaboração
internacional:

- [Guia de contribuição](../CONTRIBUTING.md)
- [Ambiente de desenvolvimento](development.md)
- [Arquitetura](architecture.md)
- [Dicionário local e snippets](dictionary-snippets.md)
- [Microfones e limites de gravação](microphone-controls.md)
- [Suporte](../SUPPORT.md)
- [Política de segurança](../SECURITY.md)

O código do Clarify usa a [Licença MIT](../LICENSE). O SoX e outras
dependências mantêm suas próprias licenças, documentadas em
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
