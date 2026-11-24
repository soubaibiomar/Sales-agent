# 07 — Voice AI Inspection (critical)

## Capability matrix
| Capability | Real? | Evidence |
|---|---|---|
| Microphone input in the browser | **No** | `voice_agent.html` has no `getUserMedia`, `MediaRecorder` or `AudioContext`. The mic button only calls `/voice/sessions`. The script block is duplicated, so each click creates two sessions (lines 393 and 531). |
| Audio capture over WebSocket | Yes (server side) | `/api/v1/voice/ws/{id}` accepts PCM frames. **Unauthenticated.** |
| VAD | Yes (energy threshold) | `audio_pipeline.py:80` |
| Barge-in | Yes (energy during playback) | `audio_pipeline.py:149` |
| Speech recognition | **Placeholder** | `transcribe_audio_chunk` returns the literal `"Audio utterance processed"` with confidence 0.94 for any loud chunk (`multilingual_voice.py:89-119`). |
| Language identification | Text heuristics | Operates on text, not audio. |
| Agent orchestration | Yes (supervisor routing) | Tool answers are fixtures. |
| Real LLM inference | Possible (4B) | Subject to the 5 s timeout / fake fallback (F-16). |
| Text-to-speech | **Synthetic waveform** | `synthesize_speech` returns sine harmonics (300/1200/2500 Hz) sized at 14 characters per second (`multilingual_voice.py:121-152`, `audio_pipeline.py:239`). |
| Audio playback | Frames sent back; the browser does not play them. | — |
| Streaming | WebSocket JSON/binary | — |
| Human takeover | Yes (session handoff + supervisor silencing) | Tests pass. |
| Session recovery | Not implemented | — |
| WebRTC | **Not implemented** | — |
| SIP/PSTN | Signature helper + G.711 codec only; no media server | `telephony.py` |

Models named in config (Whisper / Kokoro / Piper / moulsot) **are not loaded anywhere in the code**.

## The 518–569 ms latency claim
- **Where the number comes from:**
  - `scripts/benchmark_voice_pipeline.py:431-436` passes `asr_ms=110.0` as a literal ("Whisper-base CPU chunk latency").
  - LLM TTFT falls back to `380.0` when not measured.
  - `scripts/voice_reality_check.py:97-98` does the same.
  - TTS "latency" is the time to generate sine waves.
- **Verdict:** the figure is a **sum of one constant, one fallback constant and micro-benchmarks of placeholder code**. It is **not** an audio-to-audio measurement.
- **What we can measure instead:** a real lower bound for the LLM step alone on this laptop is 674–744 ms TTFT warm, and 15 s cold, for 4B (report 06). That already exceeds the 600 ms target before any STT or TTS.
- **Genuine local audio test (Journey G):** **not executable** — no STT/TTS model exists in the code to test.

## Security
| Control | Result |
|---|---|
| Caller verification (SAI-01/03) | **Defeated:** static `123456` accepted (SEC-PROBE-05). Caller ID is correctly treated as untrusted, but the OTP is never delivered (no SMS/WhatsApp send). |
| Manager auth (SAI-02) | Copilot routes require a JWT with `voice:copilot`. That permission is absent from every default role except `super_admin`'s wildcard. Step-up "TOTP" is a length check; tokens are not bound to tenant or user (SEC-PROBE-06/07). |
| High-risk action execution | "Executed" message, but no domain call. |
| Recording / disclosure (SAI-04) | Disclosure text exists. `recording_consent=True` is hardcoded on the WS and SIP inbound paths (`voice.py:449,630`). Retention job not found. |
| Telephony abuse (SAI-05) | Signature verified only if the header is present; hardcoded `telephony_secret_token`; flood limiter in memory. |
| Transcript redaction | `VoicePIIRedactor` (CIN, cards, phones) — works in tests. |

## Multilingual (fr-FR, en-US, ar-MA, ary-Arab, ary-Latn, FR/Darija mix)
- **Text level:** script and keyword heuristics plus Arabizi normalisation are implemented and tested on 90 text samples.
- **Speech level:** there is **no speech-recognition accuracy evidence at all** — no audio, no WER. The `DarijaLID`, `Transliteration-Moroccan-Darija` and `moulsot` tools are configuration strings only.

## Verdict
Voice AI does **not** work end to end. The deliverable is a voice *session/security skeleton* with real VAD, G.711 and turn logic. Its two critical security controls are bypassable.
