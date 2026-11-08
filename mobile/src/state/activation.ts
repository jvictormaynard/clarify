import type { MicrophoneActivation, Snapshot } from '../../modules/clarify-core';

interface ActivationCore {
  activate(): Promise<MicrophoneActivation>;
  getSnapshot(): Promise<Snapshot>;
  returnToSource(token: string): Promise<boolean>;
}

export async function activateMicrophone(core: ActivationCore, token?: string): Promise<Snapshot> {
  const result = await core.activate();
  if (!result.active) throw new Error(result.message ?? "Não foi possível ativar o microfone. Tente novamente.");
  const state = await core.getSnapshot();
  if (!state.sessionActive) throw new Error(state.message ?? "O áudio foi interrompido. Ative o microfone novamente.");
  if (token) await core.returnToSource(token);
  return state;
}
