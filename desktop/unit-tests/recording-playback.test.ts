import assert from "node:assert/strict";
import { test, vi } from "vitest";
const { begin, end } = vi.hoisted(() => ({ begin: vi.fn(), end: vi.fn(async () => true) }));
vi.mock("../src/settings/bridge", () => ({ beginRecordingPlayback: begin, endRecordingPlayback: end }));
import { startRecordingPlayback } from "../src/settings/recording-playback";

test("capture admission pauses audio before acknowledgement and revokes a late Play reply", async () => {
  const events: string[] = [];
  const player = document.createElement("audio");
  const pause = vi.spyOn(player, "pause").mockImplementation(() => { events.push("pause"); });
  const play = vi.spyOn(player, "play").mockResolvedValue();
  document.body.append(player);
  end.mockImplementation(async () => { events.push("ack"); return true; });
  begin.mockResolvedValueOnce("lease-playing");
  await startRecordingPlayback("recording", player);
  assert.equal(play.mock.calls.length, 1);
  document.dispatchEvent(new CustomEvent("clarify-stop-audio", { detail: "lease-playing" }));
  assert.deepEqual(events.slice(-2), ["pause", "ack"]);
  let release!: (lease: string) => void;
  begin.mockImplementationOnce(() => new Promise<string>(resolve => { release = resolve; }));
  const late = startRecordingPlayback("recording", player);
  document.dispatchEvent(new CustomEvent("clarify-stop-audio", { detail: "lease-pending" }));
  release("lease-pending");
  await assert.rejects(late, { name: "AbortError" });
  assert.equal(play.mock.calls.length, 1, "A delayed reply must not start speaker audio after capture admission");
  assert.ok(pause.mock.calls.length >= 2);
  player.remove();
});
