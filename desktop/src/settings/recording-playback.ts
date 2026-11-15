import { beginRecordingPlayback, endRecordingPlayback } from "./bridge";

let current: { player: HTMLAudioElement; lease: string } | null = null;
const revoked = new Set<string>();

export async function releaseRecordingPlayback(player: HTMLAudioElement) {
  if (current?.player !== player) return;
  const { lease } = current;
  current = null;
  await endRecordingPlayback(lease);
}

export async function stopRecordingPlayback(lease: string) {
  revoked.add(lease);
  if (revoked.size > 256) revoked.delete(revoked.values().next().value!);
  // Pause synchronously before the native admission waiter can resume capture.
  for (const player of document.querySelectorAll("audio")) player.pause();
  if (current?.lease === lease) current = null;
  await endRecordingPlayback(lease);
}

document.addEventListener("clarify-stop-audio", event => {
  const lease = (event as CustomEvent<unknown>).detail;
  if (typeof lease === "string") void stopRecordingPlayback(lease).catch(() => {});
});

export async function startRecordingPlayback(id: string, player: HTMLAudioElement) {
  if (current) {
    const previous = current.player;
    previous.pause();
    await releaseRecordingPlayback(previous);
  }
  const lease = await beginRecordingPlayback(id);
  if (revoked.has(lease)) {
    await endRecordingPlayback(lease);
    throw new DOMException("Playback stopped for recording", "AbortError");
  }
  current = { player, lease };
  try { await player.play(); }
  catch (error) { await releaseRecordingPlayback(player); throw error; }
}
