// AudioContext resamples both inputs to mono 16 kHz before they reach this node.
class MeetingPcm extends AudioWorkletProcessor {
  constructor({processorOptions}) {
    super();
    this.samples = new Int16Array(5120);
    this.used = 0;
    this.started = false;
    this.system = processorOptions?.separateSystem ? new Int16Array(this.samples.length) : null;
    this.pending = 0;
    this.closed = false;
    this.port.onmessage = ({data}) => {
      if (data === "begin") {
        this.started = true;
        return;
      }
      if (data === "ack") {
        this.pending = Math.max(0, this.pending - 1);
        return;
      }
      if (data !== "drain") return;
      this.closed = true;
      this.send();
      this.port.postMessage("drained");
    };
  }

  send() {
    if (!this.used) return;
    if (this.pending >= 25) {
      this.closed = true;
      this.used = 0;
      this.port.postMessage("overload");
      return;
    }
    const pcm = this.samples.slice(0, this.used);
    if (this.system) {
      const system = this.system.slice(0, this.used);
      this.port.postMessage({ pcm: pcm.buffer, system: system.buffer }, [pcm.buffer, system.buffer]);
    } else {
      this.port.postMessage({ pcm: pcm.buffer }, [pcm.buffer]);
    }
    this.pending++;
    this.used = 0;
  }

  process([microphone, system], [output]) {
    if (this.closed) return false;
    if (!this.started) return true;
    for (let index = 0; index < output[0].length; index++) {
      const mic = microphone[0]?.[index] ?? 0;
      const remote = system[0]?.[index] ?? 0;
      this.samples[this.used] = Math.round(Math.min(1, Math.max(-1, mic)) * 32767);
      if (this.system) this.system[this.used] = Math.round(Math.min(1, Math.max(-1, remote)) * 32767);
      this.used++;
      if (this.used === this.samples.length) {
        this.send();
        if (this.closed) return false;
      }
    }
    // The connected output is silent. It keeps processing without monitoring
    // input through the speakers or feeding it into system audio again.
    return true;
  }
}

registerProcessor("meeting-pcm", MeetingPcm);
