"""
Measured audio-to-audio voice turn benchmark (inspection finding F-15).

Replaces the earlier "518-569 ms" figure, which was a sum of hardcoded constants.
For each language: a spoken customer request (Piper-synthesized - NOT a consented human
recording, so recognition accuracy here is optimistic) is transcribed by faster-whisper
(CPU int8), answered by the local LLM through the real Ollama provider (warm qwen3.5:4b),
and the answer is synthesized by Piper. Every stage is timed with perf_counter.

Usage: python scripts/benchmark_real_voice_turn.py <output.json>
"""
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.backend.voice.multilingual_voice import MultilingualVoiceEngine  # noqa: E402
from src.ai.providers.ollama_provider import OllamaProvider  # noqa: E402

CASES = [
    ("fr-FR", "Bonjour, quel est le délai de livraison à Casablanca ?"),
    ("fr-FR", "Je voudrais un devis pour dix ordinateurs portables."),
    ("en-US", "Hello, can you give me an update on my order status?"),
    ("en-US", "Do you have solar panels in stock this week?"),
    ("ar-MA", "مرحبا، أريد معرفة موعد توصيل طلبي."),
    ("ar-MA", "هل لديكم ألواح شمسية متوفرة في المخزن؟"),
]


def wer(ref: str, hyp: str) -> float:
    import re
    norm = lambda t: re.sub(r"[^\w\s]", " ", t.lower()).split()
    r, h = norm(ref), norm(hyp)
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    return round(d[len(r)][len(h)] / max(1, len(r)), 3)


async def main(out_path: str) -> None:
    provider = OllamaProvider()
    # Warm-up (not measured): load ASR, voices and the 4B model once.
    warm_audio, _ = MultilingualVoiceEngine.synthesize_speech("Bonjour", "fr-FR")
    MultilingualVoiceEngine.transcribe_audio_chunk(warm_audio, "fr-FR")
    for lang in ("en-US", "ar-MA"):
        MultilingualVoiceEngine.synthesize_speech("ok", lang)
    await provider.generate("Réponds: ok", max_tokens=4, timeout=180)  # cold start under memory pressure

    runs = []
    for lang, text in CASES:
        caller_audio, _ = MultilingualVoiceEngine.synthesize_speech(text, lang)
        t0 = time.perf_counter()
        asr = MultilingualVoiceEngine.transcribe_audio_chunk(caller_audio, lang)
        t1 = time.perf_counter()
        llm = await provider.generate(
            f"Tu es un assistant commercial. Réponds en une phrase courte, dans la langue du client, sans inventer de prix: {asr['text']}",
            max_tokens=48, temperature=0.2
        )
        t2 = time.perf_counter()
        reply_audio, meta = MultilingualVoiceEngine.synthesize_speech(llm["content"], lang)
        t3 = time.perf_counter()
        runs.append({
            "language": lang, "reference_text": text, "transcript": asr["text"], "wer": wer(text, asr["text"]),
            "caller_audio_s": round(caller_audio.duration_ms / 1000, 2),
            "asr_ms": round((t1 - t0) * 1000, 1), "llm_ms": round((t2 - t1) * 1000, 1),
            "llm_ttft_ms": llm.get("metrics", {}).get("ttft_ms"), "tts_ms": round((t3 - t2) * 1000, 1),
            "total_turn_ms": round((t3 - t0) * 1000, 1), "reply_audio_s": round(reply_audio.duration_ms / 1000, 2),
            "tts_engine": meta["tts_engine"], "reply_text": llm["content"][:200],
        })
        print(runs[-1]["language"], runs[-1]["total_turn_ms"], "ms, WER", runs[-1]["wer"])

    totals = [r["total_turn_ms"] for r in runs]
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "hardware": "i7-13620H, RTX 4060 Laptop 8 GB (LLM on GPU), ASR/TTS on CPU, 16 GB RAM",
        "engines": {"asr": "faster-whisper small int8 (CPU)", "llm": "qwen3.5:4b via Ollama (warm)", "tts": "Piper medium voices (CPU)"},
        "caveat": "Caller audio is Piper-synthesized, not consented human recordings: WER is optimistic and not a production accuracy claim. Measured end-to-end in one process; no network/telephony latency included.",
        "target_turn_latency_ms": 600,
        "summary": {
            "turns": len(runs),
            "total_turn_ms_median": round(statistics.median(totals), 1),
            "total_turn_ms_max": max(totals),
            "asr_ms_median": round(statistics.median(r["asr_ms"] for r in runs), 1),
            "llm_ms_median": round(statistics.median(r["llm_ms"] for r in runs), 1),
            "tts_ms_median": round(statistics.median(r["tts_ms"] for r in runs), 1),
            "wer_by_language": {lang: round(statistics.mean(r["wer"] for r in runs if r["language"] == lang), 3)
                                for lang in sorted({r["language"] for r in runs})},
            "meets_600ms_target": max(totals) < 600,
        },
        "runs": runs,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "evidence/claude-inspection/benchmarks/real_voice_turn_benchmark.json"))
