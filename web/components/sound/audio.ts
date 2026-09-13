/**
 * Short synthesized cues, no audio files. A cue plays only when sound is switched on and a real run
 * event has just arrived.
 */
export type Cue = "stamp" | "paper" | "chain";

let context: AudioContext | null = null;

/** Creates or resumes the audio context. Call it from a click so the browser allows playback. */
export function unlockAudio() {
  if (typeof window === "undefined") return;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return;
  context ??= new Ctor();
  void context.resume();
}

function noiseBuffer(ctx: AudioContext, seconds: number): AudioBuffer {
  const buffer = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * seconds), ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
  return buffer;
}

function envelope(ctx: AudioContext, start: number, peak: number, attack: number, release: number): GainNode {
  const gain = ctx.createGain();
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(peak, start + attack);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + attack + release);
  gain.connect(ctx.destination);
  return gain;
}

function stamp(ctx: AudioContext, t: number) {
  const thud = ctx.createOscillator();
  thud.type = "sine";
  thud.frequency.setValueAtTime(140, t);
  thud.frequency.exponentialRampToValueAtTime(45, t + 0.18);
  thud.connect(envelope(ctx, t, 0.5, 0.005, 0.24));
  thud.start(t);
  thud.stop(t + 0.3);

  const slap = ctx.createBufferSource();
  slap.buffer = noiseBuffer(ctx, 0.08);
  const low = ctx.createBiquadFilter();
  low.type = "lowpass";
  low.frequency.value = 900;
  slap.connect(low);
  low.connect(envelope(ctx, t, 0.3, 0.003, 0.07));
  slap.start(t);
}

function paper(ctx: AudioContext, t: number) {
  const rustle = ctx.createBufferSource();
  rustle.buffer = noiseBuffer(ctx, 0.24);
  const band = ctx.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = 2500;
  band.Q.value = 0.8;
  rustle.connect(band);
  band.connect(envelope(ctx, t, 0.12, 0.03, 0.19));
  rustle.start(t);
}

function chain(ctx: AudioContext, t: number) {
  for (const [offset, frequency] of [
    [0, 2200],
    [0.07, 3300],
  ] as const) {
    const click = ctx.createOscillator();
    click.type = "triangle";
    click.frequency.value = frequency;
    click.connect(envelope(ctx, t + offset, 0.15, 0.002, 0.04));
    click.start(t + offset);
    click.stop(t + offset + 0.06);
  }
}

export function playCue(cue: Cue) {
  if (!context) unlockAudio();
  if (!context) return;
  try {
    const t = context.currentTime + 0.01;
    if (cue === "stamp") stamp(context, t);
    else if (cue === "paper") paper(context, t);
    else chain(context, t);
  } catch (err) {
    console.warn("[PriceQuorum] a sound cue could not play", err);
  }
}
