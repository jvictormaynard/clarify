import { useEffect, useSyncExternalStore } from "react";
import { electron, isMacDesktop } from "../platform";
import workletUrl from "./pcm-worklet.js?url&no-inline";

export type MeetingEntry = {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  startedAt: number | null;
  duration: number;
  status: "draft" | "starting" | "recording" | "paused" | "finalizing" | "completed" | "interrupted";
  source: "mic" | "system";
  error: string;
  hasSummary: boolean;
  systemAudio?: boolean;
  lightMode?: boolean;
  speakerLabels?: boolean;
  liveSpeakerLabels?: boolean;
  recoveringOverlap?: boolean;
  microphone?: string;
};
export const LOCAL_MICROPHONE = -1;
export const SYSTEM_AUDIO = -2;
export type TranscriptTurn = { start: number; end?: number; text: string; speaker?: number | null; overlap?: boolean; source?: Source };

export type Meeting = MeetingEntry & {
  notes: string;
  summary: string;
  segments: TranscriptTurn[];
  originalSegments?: TranscriptTurn[];
  overlapRevision?: number;
  speakers?: Record<number, string>;
};
export type MeetingState = {
  supported: boolean;
  installed: boolean;
  installing: boolean;
  speakersInstalled?: boolean;
  installingSpeakers?: boolean;
  overlapSupported?: boolean;
  overlapInstalled?: boolean;
  installingOverlap?: boolean;
  installProgress: number;
  active: MeetingEntry | null;
  partial: string;
  partialTurns?: TranscriptTurn[];
  overlapRevision?: number;
  projectedPartial?: TranscriptTurn[] | null;
  generating: string | null;
  summaryAvailable: boolean;
  summaryPending: string | null;
  summaryError: { id: string; code: string } | null;
  summaryRevision: number;
  libraryRevision: number;
  error: string;
  loopback: boolean;
  captureId?: string | null;
  interruptedId?: string | null;
  releasing?: boolean;
};
type CaptureAdmission = {
  captureId: string;
  microphone: string | null;
  microphoneMayBeTruncated?: boolean;
};

type MeetingPatch = Partial<Pick<Meeting, "title" | "notes" | "summary">>;
type Template = "brief" | "decisions" | "followup";
type Source = Meeting["source"];

function call<T>(method: string, ...args: unknown[]) {
  const desktop = electron();
  if (!desktop) return Promise.reject(new Error("capture_unavailable"));
  return desktop.call<T>("meetings", method, args).catch(error => {
    const message = error instanceof Error ? error.message : "";
    const code = /(?:^|Error: )([a-z_]+)$/.exec(message)?.[1];
    throw code ? new Error(code) : error;
  });
}

let meetingState: MeetingState | null = null;
let initialized = false;
let revision = 0;
const listeners = new Set<() => void>();

function update(state: MeetingState) {
  revision++;
  meetingState = state;
  listeners.forEach(listener => listener());
}

function initialize() {
  if (initialized || !electron()) return;
  initialized = true;
  const unsubscribe = electron()!.subscribe(message => {
    if (message.event === "meetings") update(message.state as unknown as MeetingState);
  });
  const requestedAt = revision;
  void call<MeetingState>("state").then(state => {
    if (revision === requestedAt) update(state);
  }).catch(() => {
    if (revision === requestedAt) {
      unsubscribe();
      initialized = false;
    }
  });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useMeetings() {
  useEffect(initialize, []);
  return useSyncExternalStore(subscribe, () => meetingState);
}

export const meetingList = (query: string, offset: number) => call<MeetingEntry[]>("list", query, offset);
export const meetingGet = (id: string) => call<Meeting | null>("get", id);
export const meetingCreate = () => call<Meeting>("create");
export const meetingSave = (id: string, patch: MeetingPatch) => call<Meeting>("save", id, patch);
export const meetingDelete = (id: string) => call<void>("delete", id);
export const meetingInstall = () => call<void>("install");
export const meetingInstallSpeakers = () => call<void>("installSpeakers");
export const meetingInstallOverlap = () => call<void>("installOverlap");
export const meetingNameSpeaker = (id: string, speaker: number, name: string) => call<Meeting>("nameSpeaker", id, speaker, name);
export const meetingCancelInstall = () => call<void>("cancelInstall");
export const meetingSummarize = (id: string, template: Template) => call<void>("summarize", id, template);
export const meetingCopy = (text: string) => call<void>("copy", text);

let capture: MeetingCapture | null = null;
let finishing = false;

class MeetingCapture {
  readonly context = new AudioContext({ sampleRate: 16000, latencyHint: "interactive" });
  readonly streams: MediaStream[] = [];
  private node: AudioWorkletNode | null = null;
  private pending = Promise.resolve();
  private queued = 0;
  private drained: (() => void) | null = null;
  private closed = false;
  private unsubscribe: () => void = () => {};
  private rejectStartup: (() => void) | null = null;
  private rejectAcquisition: (() => void) | null = null;
  private captureId = "";
  private pendingMedia = 0;
  private released = false;

  constructor(readonly id: string) {}

  private remember(stream: MediaStream) {
    for (const track of stream.getVideoTracks()) track.stop();
    if (this.closed) {
      stream.getTracks().forEach(track => track.stop());
      throw new Error("capture_interrupted");
    }
    this.streams.push(stream);
    const track = stream.getAudioTracks()[0];
    if (!track || track.readyState === "ended") throw new Error("capture_interrupted");
    track.addEventListener("ended", () => void this.interrupt("capture_interrupted"), { once: true });
    return stream;
  }

  private requestMedia(request: () => Promise<MediaStream>) {
    if (this.closed) return Promise.reject(new Error("capture_interrupted"));
    this.pendingMedia++;
    return Promise.resolve().then(() => {
      if (this.closed) throw new Error("capture_interrupted");
      return request();
    }).then(stream => this.remember(stream)).finally(() => {
      this.pendingMedia--;
      this.releaseIfReady();
    });
  }

  private releaseIfReady() {
    if (!this.closed || this.pendingMedia || !this.captureId || this.released) return;
    this.released = true;
    void electron()?.window("meetingAudioReleased", this.captureId).catch(() => {});
  }

  private async microphone(preferred: string | null, separateSystem: boolean, mayBeTruncated = false) {
    const options: MediaTrackConstraints = {
      channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
    };
    const open = (constraints: MediaTrackConstraints) => {
      // Prefer system-wide cancellation on the chosen device. If it cannot
      // provide that mode, Chromium skips this set and keeps the same input.
      const audio = separateSystem ? {
        ...constraints,
        advanced: [{deviceId: constraints.deviceId ?? "default", echoCancellation: "all"}],
      } : constraints;
      return this.requestMedia(() => navigator.mediaDevices.getUserMedia({audio, video: false}));
    };
    try {
      if (!preferred) return await open(options);
      const normalize = (label: string) => label.normalize("NFC").trim().toLowerCase();
      const selected = normalize(preferred);
      // WaveAudio can truncate device names to 31 characters. Match this
      // prefix against concrete inputs and reject it if more than one fits.
      const truncated = mayBeTruncated && preferred.length === 31;
      const match = async () => (await navigator.mediaDevices.enumerateDevices()).filter(device =>
        device.kind === "audioinput" && device.deviceId !== "default" && device.deviceId !== "communications"
        && (truncated ? normalize(device.label).startsWith(selected) : normalize(device.label) === selected),
      );
      let candidates = await match();
      if (this.closed) throw new Error("capture_interrupted");
      if (!candidates.length) {
        // Chromium may redact names until an input stream grants access. This
        // probe never connects to the worklet and is released before capture.
        const probe = await open(options);
        try { candidates = await match(); }
        finally { probe.getTracks().forEach(track => track.stop()); }
      }
      if (this.closed || candidates.length !== 1) throw new Error("microphone_selected_unavailable");
      return await open({...options, deviceId: {exact: candidates[0].deviceId}});
    } catch {
      throw new Error(preferred ? "microphone_selected_unavailable" : "microphone_unavailable");
    }
  }

  async open(source: Source, method: "start" | "startWithOverlap" | "resume") {
    let accepted = false;
    let seen = false;
    const acquire = async () => {
      this.unsubscribe = subscribe(() => {
        if (meetingState?.active?.id === this.id && ["starting", "recording"].includes(meetingState.active.status)) {
          seen = true;
        } else if (seen || accepted) {
          this.close();
        }
      });
      // Resume the context under the initiating gesture, before crossing IPC.
      const audioReady = this.context.resume().catch(() => {});
      const result = method === "resume" ? await call<CaptureAdmission>(method, this.id)
        : await call<CaptureAdmission>(method, this.id, source);
      this.captureId = result.captureId;
      accepted = true;
      if (this.closed) {
        this.releaseIfReady();
        throw new Error("capture_interrupted");
      }
      // Windows loopback needs a recent gesture. On macOS the backend opens an audio-only tap.
      const separateSystem = source === "system" && !isMacDesktop();
      const display = separateSystem ? this.requestMedia(() => navigator.mediaDevices.getDisplayMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        video: { width: 32, height: 32, frameRate: 1 },
      })).catch(() => {
        throw new Error("system_audio_unavailable");
      }) : Promise.resolve(null);
      const microphone = this.microphone(result.microphone, separateSystem, result.microphoneMayBeTruncated);
      const [systemStream, micStream] = await Promise.all([display, microphone, audioReady]);
      if (this.closed || this.context.state !== "running") throw new Error("capture_interrupted");
      await this.context.audioWorklet.addModule(workletUrl);
      if (this.closed) throw new Error("capture_interrupted");
      if (systemStream && !systemStream.getAudioTracks().length) throw new Error("system_audio_unavailable");
      const node = this.node = new AudioWorkletNode(this.context, "meeting-pcm", {
        numberOfInputs: 2, numberOfOutputs: 1, outputChannelCount: [1],
        channelCount: 1, channelCountMode: "explicit",
        processorOptions: {separateSystem},
      });
      node.port.onmessage = event => this.receive(event.data, separateSystem);
      this.context.createMediaStreamSource(micStream).connect(node, 0, 0);
      if (systemStream) this.context.createMediaStreamSource(systemStream).connect(node, 0, 1);
      await call("mediaReady", this.id, micStream.getAudioTracks()[0].label.slice(0, 256), this.captureId);
      await this.waitForRecording();
      if (this.closed) throw new Error("capture_interrupted");
      // Queue nothing while the native runtime is warming up.
      node.connect(this.context.destination);
      node.port.postMessage("begin");
    };
    try {
      const cancel = new Promise<never>((_resolve, reject) => {
        this.rejectAcquisition = () => reject(new Error(meetingState?.error || "capture_interrupted"));
      });
      await Promise.race([acquire(), cancel]);
    } catch (error) {
      const reason = error instanceof Error ? error.message : "";
      if (!this.closed) {
        if (accepted) {
          await this.interrupt(["microphone_unavailable", "microphone_selected_unavailable", "system_audio_unavailable"].includes(reason)
            ? reason : "capture_interrupted");
        } else {
          this.close();
        }
      }
      throw error;
    } finally {
      this.rejectAcquisition = null;
    }
  }

  private waitForRecording() {
    if (this.closed) return Promise.reject(new Error("capture_interrupted"));
    if (meetingState?.active?.id === this.id && meetingState.active.status === "recording") return Promise.resolve();
    return new Promise<void>((resolve, reject) => {
      const unsubscribe = subscribe(() => {
        if (meetingState?.active?.id === this.id && meetingState.active.status === "recording") finish(true);
      });
      const timer = window.setTimeout(() => finish(false), 56_000);
      const finish = (ready: boolean) => {
        unsubscribe();
        window.clearTimeout(timer);
        this.rejectStartup = null;
        if (ready) resolve();
        else reject(new Error(meetingState?.error || "model_start_failed"));
      };
      this.rejectStartup = () => finish(false);
    });
  }

  private receive(data: unknown, separateSystem: boolean) {
    if (data === "overload") {
      void this.interrupt("capture_overload");
      return;
    }
    if (data === "drained") {
      this.drained?.();
      return;
    }
    if (this.closed || typeof data !== "object" || !data || !("pcm" in data) || !(data.pcm instanceof ArrayBuffer)) return;
    const pcm = data.pcm;
    const system = "system" in data && data.system instanceof ArrayBuffer ? data.system : null;
    if (separateSystem && (!system || system.byteLength !== pcm.byteLength)) {
      void this.interrupt("capture_interrupted");
      return;
    }
    if (this.queued >= 25) {
      void this.interrupt("capture_overload");
      return;
    }
    this.queued++;
    this.pending = this.pending.then(async () => {
      if (!this.closed) {
        const encode = (buffer: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(buffer)));
        if (system) await call("feedChannels", this.id, encode(pcm), encode(system), this.captureId);
        else await call("feed", this.id, encode(pcm), false, this.captureId);
        this.node?.port.postMessage("ack");
      }
    }).catch(error => {
      if (!this.closed) {
        const reason = error instanceof Error && ["system_audio_unavailable", "capture_overload"].includes(error.message)
          ? error.message : "capture_interrupted";
        void this.interrupt(reason);
      }
    }).finally(() => { this.queued--; });
  }

  async finish(stop: () => Promise<void>) {
    const node = this.node;
    if (node && meetingState?.active?.status === "recording") {
      await new Promise<void>(resolve => {
        const timer = window.setTimeout(() => this.drained?.(), 500);
        this.drained = () => {
          window.clearTimeout(timer);
          this.drained = null;
          resolve();
        };
        node.port.postMessage("drain");
      });
    }
    // Hardware is released before finalization, while queued PCM drains.
    this.streams.splice(0).forEach(stream => stream.getTracks().forEach(track => track.stop()));
    await this.pending;
    this.close();
    await stop();
  }

  private async interrupt(reason: string) {
    this.close();
    if (this.captureId) await call("interrupt", this.id, reason, this.captureId).catch(() => {});
  }

  private close() {
    if (this.closed) return;
    this.closed = true;
    this.unsubscribe();
    this.rejectAcquisition?.();
    this.rejectStartup?.();
    this.drained?.();
    if (this.node) this.node.port.onmessage = null;
    this.streams.splice(0).forEach(stream => stream.getTracks().forEach(track => track.stop()));
    this.releaseIfReady();
    void this.context.close().catch(() => {});
    if (capture === this) capture = null;
  }
}

export async function meetingStart(id: string, source: Source, recoverOverlap = false) {
  initialize();
  if (capture) throw new Error("capture_busy");
  const next = capture = new MeetingCapture(id);
  await next.open(source, recoverOverlap ? "startWithOverlap" : "start");
}

export async function meetingResume(id: string) {
  const active = meetingState?.active;
  if (!active || active.id !== id || active.status !== "paused") throw new Error("capture_unavailable");
  if (capture) throw new Error("capture_busy");
  const next = capture = new MeetingCapture(id);
  await next.open(active.source, "resume");
}

async function finishMeeting(id: string, command: () => Promise<void>) {
  if (finishing) throw new Error("capture_busy");
  finishing = true;
  try {
    if (capture?.id === id) await capture.finish(command);
    else await command();
  } finally {
    finishing = false;
  }
}

export const meetingPause = (id: string) => finishMeeting(id, () => call<void>("pause", id));
export const meetingStop = (id: string, template?: Template) => finishMeeting(id, () =>
  template ? call<void>("stopAndGenerate", id, template) : call<void>("stop", id));

export async function meetingStopFromDock(id: string) {
  const active = meetingState?.active;
  if (finishing || active?.id !== id || !["recording", "paused"].includes(active.status)) return;
  await meetingStop(id);
}
