import {t, uiLanguage} from './i18n';
// Pill-only copy stays within the migration slice. Shared Settings copy is unchanged.
const labels: Record<string, {en: string; es: string}> = {
  'Sem microfones': {en: 'No microphones', es: 'Sin micrófonos'},
  'Ações de texto': {en: 'Text actions', es: 'Acciones de texto'},
  'Instalar atualização': {en: 'Install update', es: 'Instalar actualización'},
  'Iniciar gravação': {en: 'Start recording', es: 'Iniciar grabación'},
  'Parar gravação': {en: 'Stop recording', es: 'Detener grabación'},
  'Cancelar gravação': {en: 'Cancel recording', es: 'Cancelar grabación'},
  'Iniciando': {en: 'Starting', es: 'Iniciando'},
  'Traduzir para': {en: 'Translate to', es: 'Traducir a'},
  'Ver resultado': {en: 'Show result', es: 'Ver resultado'},
  'Mais opções': {en: 'More options', es: 'Más opciones'},
  'Ditar': {en: 'Dictate', es: 'Dictar'},
  'Concluído': {en: 'Done', es: 'Listo'},
  'Idioma de saída': {en: 'Output language', es: 'Idioma de salida'},
  'Idioma': {en: 'Language', es: 'Idioma'},
  'Colar última transcrição': {en: 'Paste last transcription', es: 'Pegar última transcripción'},
  'Transcrever arquivos': {en: 'Transcribe files', es: 'Transcribir archivos'},
  'Sair': {en: 'Quit', es: 'Salir'},
};
export function pillText(source: string) {
  const label = labels[source];
  return label ? uiLanguage === 'pt' ? source : label[uiLanguage] : t(source);
}
