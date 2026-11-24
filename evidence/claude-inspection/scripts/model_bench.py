"""Bounded real-inference benchmark against local Ollama (no project code mutated).
Measures cold/warm TTFT, tokens/s, total duration, peak VRAM (nvidia-smi sampling), peak host RAM used.
Then tests 4B/9B co-residency through the project's own OllamaProvider in a fresh process."""
import json, time, threading, subprocess, sys, urllib.request, os
BASE = "http://127.0.0.1:11434"
OUT = sys.argv[1]; REPO = sys.argv[2]

def post(path, body, stream=False, timeout=300):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)

def ps():
    return [(m["name"], m.get("size_vram", 0)) for m in json.load(urllib.request.urlopen(BASE + "/api/ps", timeout=5))["models"]]

class Sampler(threading.Thread):
    def __init__(s): super().__init__(daemon=True); s.stop = False; s.vram = 0; s.ram_used = 0
    def run(s):
        while not s.stop:
            try:
                v = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True, timeout=5)
                s.vram = max(s.vram, int(v.strip().splitlines()[0]))
                m = subprocess.check_output(["powershell", "-NoProfile", "-Command",
                    "$o=Get-CimInstance Win32_OperatingSystem; [int](($o.TotalVisibleMemorySize-$o.FreePhysicalMemory)/1024)"], text=True, timeout=10)
                s.ram_used = max(s.ram_used, int(m.strip()))
            except Exception: pass
            time.sleep(0.5)

def unload(m):
    try: post("/api/generate", {"model": m, "keep_alive": 0}).read()
    except Exception: pass

PROMPT = "Réponds en français en 3 phrases: quels sont les avantages d'un kit solaire 400W pour une PME à Casablanca ?"
def run(model, label):
    smp = Sampler(); smp.start(); t0 = time.perf_counter(); ttft = None; n = 0; final = {}
    with post("/api/generate", {"model": model, "prompt": PROMPT, "stream": True, "think": False,
                                "options": {"num_predict": 128, "num_ctx": 4096, "temperature": 0.2}}) as r:
        for line in r:
            d = json.loads(line)
            if ttft is None and (d.get("response") or d.get("thinking")): ttft = time.perf_counter() - t0
            if d.get("done"): final = d
    total = time.perf_counter() - t0; smp.stop = True; smp.join(2)
    ev, evd = final.get("eval_count", 0), final.get("eval_duration", 1)
    return {"label": label, "model": model, "ttft_ms": round((ttft or total) * 1000, 1), "total_ms": round(total * 1000, 1),
            "load_duration_ms": round(final.get("load_duration", 0) / 1e6, 1), "eval_tokens": ev,
            "tokens_per_s": round(ev / (evd / 1e9), 2) if evd else None, "peak_vram_mib": smp.vram,
            "peak_host_ram_used_mib": smp.ram_used, "resident_after": ps()}

res = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "prompt": PROMPT, "num_predict": 128, "runs": []}
for m in ("qwen3.5:4b", "qwen3.5:9b-q4_K_M"): unload(m)
time.sleep(2)
res["runs"].append(run("qwen3.5:4b", "4B cold"))
res["runs"].append(run("qwen3.5:4b", "4B warm #1"))
res["runs"].append(run("qwen3.5:4b", "4B warm #2"))
unload("qwen3.5:4b"); time.sleep(2)
res["runs"].append(run("qwen3.5:9b-q4_K_M", "9B cold (4B evicted first)"))
unload("qwen3.5:9b-q4_K_M"); time.sleep(2)

# Co-residency test: another process/worker leaves 4B resident; fresh project process asks for 9B.
post("/api/generate", {"model": "qwen3.5:4b", "prompt": "ok", "stream": False, "keep_alive": "10m", "options": {"num_predict": 4}}).read()
before = ps()
seen = []; stop = False
def watch():
    while not stop:
        try: seen.append(ps())
        except Exception: pass
        time.sleep(0.3)
w = threading.Thread(target=watch, daemon=True); w.start()
code = ("import asyncio,sys,json; sys.path.insert(0, sys.argv[1]);"
        "from src.ai.providers.ollama_provider import OllamaProvider;"
        "r=asyncio.run(OllamaProvider().generate('Dis bonjour.', model='qwen3.5:9b-q4_K_M', max_tokens=16, timeout=120));"
        "print(json.dumps({'model':r.get('model'),'notice':r.get('notice'),'content':(r.get('content') or '')[:120]}))")
p = subprocess.run([sys.executable, "-c", code, REPO], capture_output=True, text=True, timeout=400)
stop = True; w.join(2)
both = [s for s in seen if {"qwen3.5:4b", "qwen3.5:9b-q4_K_M"} <= {n for n, _ in s}]
res["coresidency_test"] = {"resident_before_project_call": before, "provider_stdout": p.stdout.strip()[-400:],
                           "provider_stderr_tail": p.stderr.strip()[-300:], "max_models_resident_simultaneously": max((len(s) for s in seen), default=0),
                           "snapshots_with_4B_and_9B_both_resident": len(both), "example_snapshot": both[0] if both else (seen[-1] if seen else None)}
for m in ("qwen3.5:4b", "qwen3.5:9b-q4_K_M"): unload(m)
json.dump(res, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps(res, indent=1, ensure_ascii=False))
