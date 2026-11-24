/* AudioWorklet: converts microphone Float32 samples (AudioContext at 16 kHz) into
 * 20 ms little-endian 16-bit PCM frames posted to the main thread (F-15 / F-20). */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frameSize = 320; // 20 ms at 16 kHz
    this.buffer = new Int16Array(this.frameSize);
    this.offset = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) { return true; }
    for (let i = 0; i < channel.length; i++) {
      const s = Math.max(-1, Math.min(1, channel[i]));
      this.buffer[this.offset++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.offset === this.frameSize) {
        this.port.postMessage(this.buffer.buffer.slice(0));
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor);
