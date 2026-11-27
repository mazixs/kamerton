const TARGET_RATE = 16000;

export function microphoneAvailable() {
  return window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia) &&
    Boolean(window.AudioContext || window.webkitAudioContext);
}

export async function captureMicrophone({ signal, onSamples }) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  let context;
  let source;
  let node;
  let released = false;
  const chunks = [];

  function release() {
    if (released) return;
    released = true;
    signal.removeEventListener("abort", release);
    if (node) {
      if (node.port) node.port.close();
      else node.onaudioprocess = null;
      node.disconnect();
    }
    source?.disconnect();
    for (const track of stream.getTracks()) track.stop();
    if (context && context.state !== "closed") void context.close().catch(() => {});
  }

  try {
    signal.throwIfAborted();
    signal.addEventListener("abort", release, { once: true });
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    try {
      context = new AudioContext({ sampleRate: TARGET_RATE });
    } catch (error) {
      if (error.name !== "NotSupportedError") throw error;
      context = new AudioContext();
    }
    const rate = context.sampleRate;
    source = context.createMediaStreamSource(stream);
    const receive = (samples) => {
      if (released || signal.aborted) return;
      chunks.push(samples);
      onSamples(samples);
    };
    if (context.audioWorklet) {
      await context.audioWorklet.addModule(import.meta.env.BASE_URL + "capture-worklet.js");
      signal.throwIfAborted();
      node = new AudioWorkletNode(context, "capture");
      node.port.onmessage = (event) => receive(event.data);
    } else {
      node = context.createScriptProcessor(2048, 1, 1);
      node.onaudioprocess = (event) => receive(new Float32Array(event.inputBuffer.getChannelData(0)));
    }
    await context.resume();
    signal.throwIfAborted();
    source.connect(node);
    node.connect(context.destination);
    return {
      stop({ discard = false } = {}) {
        release();
        if (discard) return null;
        const size = chunks.reduce((total, chunk) => total + chunk.length, 0);
        if (size < rate * 0.25) return null;
        const samples = new Float32Array(size);
        let offset = 0;
        for (const chunk of chunks) {
          samples.set(chunk, offset);
          offset += chunk.length;
        }
        return encodeWav(resample(samples, rate, TARGET_RATE), TARGET_RATE);
      },
    };
  } catch (error) {
    release();
    throw error;
  }
}

function resample(samples, from, to) {
  if (from === to) return samples;
  const ratio = from / to;
  const output = new Float32Array(Math.floor(samples.length / ratio));
  for (let index = 0; index < output.length; index += 1) {
    const position = index * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, samples.length - 1);
    const weight = position - left;
    output[index] = samples[left] * (1 - weight) + samples[right] * weight;
  }
  return output;
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  for (const [offset, name] of [[0, "RIFF"], [8, "WAVE"], [12, "fmt "], [36, "data"]]) {
    for (let index = 0; index < name.length; index += 1) view.setUint8(offset + index, name.charCodeAt(index));
  }
  view.setUint32(4, 36 + samples.length * 2, true);
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
