// Voice rules in the browser (FR-022): record up to 30 s with the Web Audio API, downsample to
// 16 kHz mono and encode 16-bit PCM WAV here, so the server never needs ffmpeg (30 s is about
// 0.96 MB, under the 2 MB limit). Speech stays in memory: nothing is stored in the browser.
// No build step; plain ES module.

export const TARGET_RATE = 16000;
export const MAX_SECONDS = 30;

/** Average-and-decimate to `outRate` (a box low-pass, enough for speech). */
export function downsample(samples, inRate, outRate = TARGET_RATE) {
  if (inRate === outRate) return Float32Array.from(samples);
  if (inRate < outRate) throw new Error(`microphone rate ${inRate} Hz is below ${outRate} Hz`);
  const ratio = inRate / outRate;
  const n = Math.floor(samples.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += samples[j];
    out[i] = end > start ? sum / (end - start) : samples[start] || 0;
  }
  return out;
}

function writeAscii(view, offset, text) {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
}

/** Float samples in [-1, 1] -> a RIFF/WAVE file: PCM, mono, 16-bit, little-endian. */
export function encodeWav(samples, sampleRate = TARGET_RATE) {
  const dataBytes = samples.length * 2;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeAscii(view, 36, "data");
  view.setUint32(40, dataBytes, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }
  return buffer;
}

/** Recorded float chunks at `inRate` -> a 16 kHz mono WAV Blob, trimmed to 30 s. */
export function toWav(chunks, inRate, maxSeconds = MAX_SECONDS) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const all = new Float32Array(total);
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.length; }
  let pcm = downsample(all, inRate, TARGET_RATE);
  if (pcm.length > maxSeconds * TARGET_RATE) pcm = pcm.subarray(0, maxSeconds * TARGET_RATE);
  return { blob: new Blob([encodeWav(pcm, TARGET_RATE)], { type: "audio/wav" }), seconds: pcm.length / TARGET_RATE };
}

/** Microphone capture through a ScriptProcessor (works in every current browser, no worklet file). */
export class Recorder {
  static supported() {
    return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
      (window.AudioContext || window.webkitAudioContext));
  }

  constructor({ maxSeconds = MAX_SECONDS, onTick = () => {}, onLimit = () => {} } = {}) {
    this.maxSeconds = maxSeconds;
    this.onTick = onTick;
    this.onLimit = onLimit;
    this.recording = false;
  }

  async start() {
    if (this.recording) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    const Ctx = window.AudioContext || window.webkitAudioContext;
    this.ctx = new Ctx();
    this.rate = this.ctx.sampleRate;
    this.chunks = [];
    this.length = 0;
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    this.node.onaudioprocess = (e) => {
      if (!this.recording) return;
      const data = e.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(data));
      this.length += data.length;
      const seconds = this.length / this.rate;
      this.onTick(seconds);
      if (seconds >= this.maxSeconds) this.onLimit();
    };
    this.source.connect(this.node);
    this.node.connect(this.ctx.destination); // the node writes silence; needed for it to run
    this.recording = true;
  }

  async stop() {
    if (!this.recording) return null;
    this.recording = false;
    try { this.source.disconnect(); this.node.disconnect(); } catch { /* already gone */ }
    this.stream.getTracks().forEach((t) => t.stop());
    await this.ctx.close().catch(() => {});
    const out = toWav(this.chunks, this.rate, this.maxSeconds);
    this.chunks = [];
    return out;
  }
}
