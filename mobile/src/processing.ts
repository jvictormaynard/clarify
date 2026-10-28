// Native owns credentials and transport. JS uses only this nonsecret projection.
export interface ProcessingStatus {
  mode?: 'hosted' | 'computer';
  signedIn: boolean;
  processingConfigured?: boolean;
  computer?: { paired: boolean; computerID: string; computerName: string; status: string; ready: boolean; busy: boolean };
}
export function processingAvailable(account: ProcessingStatus | undefined): boolean {
  if (!account) return false;
  return account.mode === 'computer' ? account.computer?.paired === true : account.signedIn;
}
export function computerStatus(status: string | undefined): string {
  switch (status) {
    case 'ready': return 'Computador disponível';
    case 'not_ready': return 'Configure o processamento no Clarify do computador.';
    case 'revoked': return 'A conexão foi revogada. Leia outro QR no computador.';
    case 'offline': return 'Computador indisponível';
    default: return 'Conecte seu computador';
  }
}
