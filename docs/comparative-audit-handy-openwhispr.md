# Comparação: Clarify, Handy e OpenWhispr

Análise de código em 6 de setembro de 2026. Escopo: arquitetura, organização,
funcionalidades, experiência de uso, áudio e validação. Este documento propõe
mudanças; não implementa recursos nem comprova o comportamento de versões instaladas.

Seguimento: a recuperação do original após falha de refinamento foi implementada
nesta branch depois da análise. Veja [comportamento e validação](refinement-recovery.md).
As observações abaixo descrevem a base anterior a essa implementação.

## Base e limites

- Clarify: pasta de trabalho em `codex/qml-functional-parity`, HEAD
  `37b3459af95b3d6abbf682dcf2deb69efc9b981f`, com alterações locais preexistentes.
  A análise inclui essas alterações, inclusive catálogo CPU/CUDA e processamento
  experimental durante a gravação.
- Handy: código público obtido nesta análise, commit
  `bc7facea3a777869182203cfcf5c90f7a98efd99`.
- OpenWhispr: código público obtido nesta análise, commit
  `a9cf27b49bdcc9069922641ec39ac06d3483a125`.
- A referência `origin/main` do Clarify foi consultada localmente, sem `fetch`.
  Ela pode estar atrás do servidor. Não foi feita auditoria do aplicativo instalado.
- Os dois aplicativos externos não foram executados. Recursos abaixo foram
  verificados no código; facilidade de uso e ganhos de desempenho são avaliações
  ou hipóteses, não resultados de testes com usuários.

## Conclusão

O Clarify tem uma base útil para evoluir sem trocar Python/Qt por Rust/Tauri ou
Electron. Os melhores investimentos são consolidar a versão de referência,
reduzir responsabilidades da camada Qt, concluir os fluxos de recuperação e
histórico, orientar o primeiro uso e tornar as capacidades dos modelos explícitas.

O Handy é uma boa referência para ditado local e controles pequenos. O OpenWhispr
é uma referência para composição de fluxos, configuração, idiomas e expansão de
produto. Seu escopo inclui reuniões, notas e agentes; trazer esse escopo inteiro
para o Clarify aumentaria bastante a manutenção.

## 1. Consolidar o produto antes de expandir

Há divergências concretas nesta pasta:

- A referência local `origin/main` contém `RetryDictation` e
  `TranscriptionTransportError`. Os arquivos `workflows.py` e
  `spikes/pyside6/qml_runtime.py` da pasta atual não contêm esses contratos.
- `docs/history.md` descreve consulta, exportação e exclusão do histórico na
  interface. O QML atual expõe ativação e retenção, mas não localizei a página
  completa nem esses comandos no controlador de configurações.
- O README ainda descreve o ASR local como CPU, enquanto o código local já contém
  perfis e seleção CUDA. Documentos recentes também registram essas mudanças.

Isso não prova que a instalação perdeu recursos. Prova que branch, documentação
e referência de integração não representam a mesma combinação de recursos.

**Proposta:** criar uma matriz curta por recurso: serviço existente, integração
QML, teste de comportamento, validação do executável e versão publicada. Conciliar
as alterações numa base única antes de implementar novas funções. Não substituir
arquivos em bloco: a pasta contém trabalho ainda não consolidado.

**Aceite:** recuperação, modelos, histórico e atalhos funcionam juntos no mesmo
executável; a documentação descreve essa versão.

## 2. Arquitetura e organização

### Preservar o núcleo independente da interface

`workflows.py` usa comandos, estados e interfaces para provedor, áudio, clipboard,
relógio e agendamento. `provider_registry.py`, `provider_types.py` e
`provider_http.py` já separam capacidades, protocolo e transporte. Essa separação
é adequada. O Handy também separa coordenador, áudio e modelos, mas seu gerenciador
de transcrição depende de `AppHandle` e do estado Tauri. Não há motivo para copiar
esse acoplamento para o nosso núcleo.

### Dividir por responsabilidade

Contagem física de linhas na versão inspecionada, sem usar tamanho como medida
isolada de qualidade:

| Arquivo Clarify | Linhas | Responsabilidades a separar |
| --- | ---: | --- |
| `spikes/pyside6/qml_settings.py` | 2.094 | Provedores, modelos, microfone, atalhos, autostart e persistência |
| `spikes/pyside6/qml/Main.qml` | 2.053 | Janela principal, resultado e várias configurações |
| `local_asr.py` | 1.874 | Manifesto, instalação, processos, inferência e adapter |
| `spikes/pyside6/qml_runtime.py` | 1.733 | Agendamento, áudio, chamadas de modelo e armazenamento |

O Handy fornece exemplos de componentes separados para cada configuração. O
OpenWhispr separa componentes, serviços e estado, mas seu `audioManager.js` tem
5.312 linhas. A referência útil é a separação de responsabilidades, não a simples
adoção da árvore de pastas.

**Proposta incremental:** extrair controladores pequenos de configurações;
separar instalação, sessão do motor e inferência; mover a interface de produção
de `spikes/` para um pacote de desktop. Migrar imports, caminhos de recursos,
autostart, testes e empacotamento na mesma etapa. O `app.py` antigo tem 13.256
linhas, mas não é a entrada Qt de produção: não atribuir seu tamanho ao fluxo ativo.
Inventariar seus consumidores antes de arquivar código legado.

Uma estrutura possível, sem novos frameworks:

```text
clarify/
  application/       comandos, sessões e políticas dos fluxos
  providers/         contratos, catálogo e adapters
  audio/             captura, medição e preparação do áudio
  local_asr/         instalação, motores e sessões
  storage/           configurações, histórico e segredos
  desktop/           controladores Qt e QML
```

### Contrato público para o ciclo de vida do modelo

`EnginePool`, em `local_asr_catalog.py`, acessa `_lock`,
`_active_cancellations`, `_startup_cancel` e `_stop_locked` de outro objeto.
Isso liga o catálogo aos detalhes internos do gerenciador.

**Proposta:** uma interface pública de sessão com preparar, adquirir uso,
transcrever, cancelar e liberar quando ocioso. O pool solicita a operação; o
motor controla seus locks. Testar troca de modelo durante preparação, cancelamento
e medição de CPU/GPU. Não criar um sistema geral de plugins nesta etapa.

## 3. Funcionalidades e UX com benefício direto

| Proposta | Referência | Situação no Clarify | Prioridade / esforço relativo |
| --- | --- | --- | --- |
| Primeiro uso guiado: microfone → local/nuvem → modelo → ditado de teste | Handy tem seleção inicial com recomendações e estados de download | Existem telas de provedor e modelo, mas não localizei esse percurso completo | Alta / médio |
| Recuperar o texto quando só o refinamento falha | Handy mantém a transcrição se o pós-processamento opcional falhar | No fluxo de ditado inspecionado, a exceção de `rewrite` interrompe o retorno do resultado | Alta / médio |
| Concluir histórico: consultar, copiar original/final, excluir e exportar | Handy tem página, paginação, cópia e nova transcrição | O armazenamento já existe; a interface QML está incompleta em relação ao documento | Alta / médio |
| Segurar para falar, além de alternar início/fim | Handy tem modos de ativação e tratamento de soltar tecla | `supports_push_to_talk()` retorna `False` | Alta / médio |
| Tradução da interface independente do idioma falado | Ambos usam catálogos de tradução | QML contém muitos textos literais em inglês; não localizei uso de `qsTr()` | Média-alta / médio |
| Sinais opcionais de início/fim e estado claro de microfone | Handy tem feedback sonoro e controles de áudio | Há medição e teste; documentação ainda registra aceite pendente para sinais sonoros | Média / pequeno-médio |
| Presets simples de saída: transcrição fiel, pontuação, revisão | Ambos separam transcrição de processamento adicional | Clarify já possui rotas e prompts por função; falta reduzir a configuração técnica para tarefas comuns | Média / médio |

O primeiro uso deve terminar em uma ação observável: uma frase de teste transcrita
e copiada/colada corretamente. Conectar um provedor ou baixar um arquivo não prova
que o fluxo completo está pronto.

Na recuperação de refinamento, manter o original numa etapa independente e
oferecer copiar ou tentar apenas a revisão novamente. Não reenviar áudio para
repetir uma etapa de texto. A publicação continua sujeita às verificações de foco
e clipboard. Uma falha opcional não deve exigir que a pessoa dite tudo outra vez.

O histórico pode continuar desligado por padrão e guardar apenas texto. A nova
transcrição do Handy depende de áudio retido: não oferecer essa ação sem definir
retenção explícita. Busca simples pode ser uma evolução posterior; SQLite só é
necessário se o volume e os padrões de consulta justificarem a mudança.

Segurar para falar exige eventos reais de pressionar/soltar, além de testes de
repetição de tecla e cancelamento. Não basta habilitar a opção na tela. Para
acessibilidade, preservar o modo de alternância.

Manter o visual compacto do Clarify. Os padrões de configuração dos concorrentes
não exigem novas cores, decoração ou uma janela de resultado em todo ditado.

## 4. Modelos, qualidade e extensibilidade

### Capacidades por modelo e motor

O Handy consulta metadados de modelo e reconcilia capacidades com o motor carregado.
No Clarify, o registro descreve sobretudo capacidades do provedor; o catálogo
local contém Base, Small e Medium em listas fixas.

**Proposta:** um catálogo tipado que informe idiomas, vocabulário contextual,
transcrição progressiva, dispositivos, memória estimada e instalação. Distinguir
"declarado pelo modelo", "detectado no computador" e "medido neste computador".
Usar o mesmo catálogo na interface e no roteamento. A escolha CPU/GPU medida já
existente deve ser reaproveitada, não refeita.

Isso permite avaliar outro motor local sem espalhar condicionais pela interface.
Parakeet ou um motor com streaming nativo são candidatos de pesquisa, não escolhas
aprovadas. Exigir resultados em português e fala mista antes de recomendar qualquer
modelo. A existência de suporte num concorrente não comprova qualidade no nosso uso.

### Dicionário útil também no modo local

O Clarify já monta contexto de vocabulário e snippets. Contudo, a requisição de
inferência local envia formato, temperatura e idioma, sem o contexto do dicionário.
O Handy usa `initial_prompt` em modelos Whisper e tem correção textual opcional.

**Proposta:** transportar termos pelo contrato de capacidades do motor, separar
vocabulário de instruções de revisão e medir nomes, siglas e termos técnicos.
Não aplicar substituição aproximada indiscriminada: ela pode corrigir uma palavra
que já estava certa.

O OpenWhispr tem filtros específicos para repetição do próprio dicionário na saída.
Isso é evidência de um modo de falha a testar, não uma razão para apagar toda frase
que contém termos do dicionário.

### Limpeza de texto por idioma

O Handy aplica normalização e remoção de hesitações com evidência do idioma do
texto. Adotar normalização conservadora; oferecer remoção de hesitações como opção.
Palavras como "tipo" e "então" podem carregar significado em português.
Separar transcrição fiel de revisão evita uma promessa ambígua de qualidade.

## 5. Áudio: uma parte da melhoria

### Uma fonte de captura para todos os consumidores

No Qt atual, SoX grava o WAV e `sounddevice.RawInputStream` abre uma segunda
captura para o medidor. O medidor é descrito como apenas visual. Não há garantia
de que esses consumidores observem as mesmas amostras. Uma futura detecção de fala
deve usar a captura efetiva, e não inferir seu conteúdo a partir desse medidor.

O Handy tem um pipeline de captura que alimenta áudio, nível e streaming.
**Proposta:** uma fonte PCM por sessão, distribuída para arquivo/snapshot,
medidor, detecção de fala e motor progressivo. Manter buffers limitados e tirar
inferência da callback de captura. Validar drivers e dispositivos antes de trocar
o backend. O benefício principal é coerência e diagnóstico; redução de latência
precisa ser medida.

### Preparação conservadora e configurável

O Clarify grava mono PCM16 a 16 kHz. O caminho normal usa o WAV completo. O modo
experimental divide por pausas, mas mantém o PCM e não remove silêncio.

O Handy filtra não fala e preserva margens de áudio: 450 ms antes da fala e
450 ms depois no modo offline; a margem posterior para streaming é 1.650 ms.
O OpenWhispr usa Silero por contexto e deixa seu uso em ditado dependente de
ativação explícita. O código registra um problema em que cortes, combinados com
dicionário, removiam fala e produziam termos do prompt.

**Proposta:** se o benchmark justificar, começar por detectar gravação sem fala e
aparar extremidades. Depois testar redução apenas de pausas longas internas,
mantendo margens e o original até terminar a operação. Áudio de baixo volume
não é necessariamente silêncio. Denoise e controle automático de ganho também
exigem teste; não devem ser ativados apenas por parecerem melhorias.

Não foi medido ganho de velocidade nesta análise. Áudio 40% menor não implica
inferência 40% mais rápida: preparação, janelas do motor, chamadas, transferência
e refinamento também consomem tempo. Dividir em muitos trechos pode aumentar
trabalho e perder contexto de idioma ou pontuação.

## 6. Testes, diagnóstico e documentação

O Clarify já tem contratos testáveis, CI Linux/Windows, locks de dependências,
checagens de pacote e tempos locais por etapa. Preservar essa base.

Lacunas identificadas:

- Mypy cobre apenas `desktop_state.py` e `windows_hotkeys.py`.
- Ruff e compilação usam listas explícitas de arquivos; novos módulos podem ficar
  fora de partes das verificações.
- Há testes que verificam texto QML e também um teste real de carregamento e
  interação offscreen. Eles não equivalem a ditado/clipboard no Windows instalado.
- Os benchmarks documentados usam amostra sintética curta em inglês. Não são uma
  avaliação de qualidade em português nem uma medição atual feita nesta análise.

**Proposta:** ampliar tipos por fronteira, executar verificações por pacote e
acrescentar cenários de UI com teclado, escala de tela e leitor de tela. O Handy
tem Playwright para sua interface; o equivalente deve usar as ferramentas Qt,
sem migrar a interface apenas para reaproveitar esse framework.

Criar um conjunto consentido ou público de fala com transcrição de referência:
português, inglês misturado, nomes, números, frases curtas, pausas e ruído. Medir
erros de palavras e omissões importantes, tempo até colar (mediana e p95), tempo
por etapa, uso de memória e primeira execução versus motor já carregado. Testar
CPU/GPU com o mesmo áudio. Amostras sintéticas continuam úteis para regressões,
mas não devem decidir sozinhas o modelo recomendado.

Diagnóstico para suporte deve mostrar versão, modelo, dispositivo realmente usado,
etapa da falha e tempos. Excluir áudio, transcrição, credenciais e nomes pessoais.

## 7. Sequência recomendada

1. **Consolidar:** comparar branches, preservar recuperação existente, alinhar
   documentação e produzir uma base verificável. Esforço depende dos conflitos.
2. **Reduzir perda de trabalho:** separar transcrição/refinamento na recuperação
   e concluir a interface de histórico. Benefício direto, esforço médio.
3. **Simplificar uso:** primeiro ditado guiado, segurar para falar e idiomas da UI.
   Entregas independentes; esforço médio por frente.
4. **Preparar expansão:** dividir controladores, criar contrato público de motor,
   catálogo de capacidades e captura compartilhada. Fazer extrações pequenas.
5. **Validar qualidade:** dicionário local e benchmark representativo; usar os
   resultados para decidir VAD, outro modelo e streaming nativo.

Os esforços são relativos, não estimativas em dias. Não recomendo agora reuniões,
diarização, sincronização, contas/equipes, agente com captura de tela ou marketplace
de plugins. São expansões de produto com novos fluxos e custos de suporte. Também
não recomendo envio automático com Enter como padrão: colar texto e enviar uma
mensagem são ações diferentes.

## Fontes de código

Links fixados nas versões inspecionadas:

- [Handy: captura e distribuição de áudio](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/src-tauri/src/audio_toolkit/audio/recorder.rs)
- [Handy: margens de VAD](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/src-tauri/src/audio_toolkit/vad/mod.rs)
- [Handy: capacidades dos modelos](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/src-tauri/src/managers/model_capabilities.rs)
- [Handy: transcrição e limpeza](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/src-tauri/src/managers/transcription.rs)
- [Handy: recuperação de pós-processamento](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/src-tauri/src/actions.rs)
- [Handy: primeiro uso](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/src/components/onboarding/Onboarding.tsx)
- [Handy: histórico](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/src/components/settings/history/HistorySettings.tsx)
- [Handy: coordenação dos atalhos](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/src-tauri/src/transcription_coordinator.rs)
- [Handy: testes de interface](https://github.com/cjpais/Handy/blob/bc7facea3a777869182203cfcf5c90f7a98efd99/.github/workflows/playwright.yml)
- [OpenWhispr: escopo do produto](https://github.com/OpenWhispr/openwhispr/blob/a9cf27b49bdcc9069922641ec39ac06d3483a125/README.md)
- [OpenWhispr: roteamento de streaming](https://github.com/OpenWhispr/openwhispr/blob/a9cf27b49bdcc9069922641ec39ac06d3483a125/src/helpers/dictationStreamingRouting.js)
- [OpenWhispr: VAD por contexto](https://github.com/OpenWhispr/openwhispr/blob/a9cf27b49bdcc9069922641ec39ac06d3483a125/src/helpers/whisperVadConfig.js)
- [OpenWhispr: detecção de áudio sem fala](https://github.com/OpenWhispr/openwhispr/blob/a9cf27b49bdcc9069922641ec39ac06d3483a125/src/helpers/localSpeechGate.js)
- [OpenWhispr: filtro de repetição do dicionário](https://github.com/OpenWhispr/openwhispr/blob/a9cf27b49bdcc9069922641ec39ac06d3483a125/src/utils/dictionaryEchoFilter.js)
- [OpenWhispr: idiomas da interface](https://github.com/OpenWhispr/openwhispr/blob/a9cf27b49bdcc9069922641ec39ac06d3483a125/src/i18n.ts)
- [OpenWhispr: gerenciador de áudio](https://github.com/OpenWhispr/openwhispr/blob/a9cf27b49bdcc9069922641ec39ac06d3483a125/src/helpers/audioManager.js)

Evidência Clarify: `workflows.py`, `provider_types.py`, `local_asr.py`,
`local_asr_catalog.py`, `local_asr_streaming.py`, `windows_hotkeys.py`,
`spikes/pyside6/qml_runtime.py`, `spikes/pyside6/qml_settings.py`,
`spikes/pyside6/qml/Main.qml`, `spikes/pyside6/qml/ProviderSettings.qml`,
`docs/history.md`, `docs/dictionary-snippets.md`, `docs/transcription-latency.md`,
`docs/local-asr-profiles-and-streaming.md`, `pyproject.toml`,
`.github/workflows/ci.yml` e `tests/test_pyside6_qml.py`.
