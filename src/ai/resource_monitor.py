"""
Real-time resource monitor and telemetry service for local hardware constraints.
Measures host RAM, NVIDIA VRAM, inference latency (TTFT), and generation throughput.
"""
import shutil
import subprocess
import time
from typing import Dict, Any, Optional
import psutil

class HardwareTelemetry:
    """Measures and reports live host memory and GPU VRAM metrics."""
    
    @staticmethod
    def get_system_ram_mb() -> Dict[str, float]:
        """Returns host system RAM usage in Megabytes and percent."""
        mem = psutil.virtual_memory()
        return {
            "total_mb": round(mem.total / (1024 * 1024), 2),
            "used_mb": round(mem.used / (1024 * 1024), 2),
            "free_mb": round(mem.available / (1024 * 1024), 2),
            "percent_used": mem.percent
        }

    @staticmethod
    def get_gpu_vram_mb() -> Dict[str, Any]:
        """Queries NVIDIA GPU VRAM via nvidia-smi."""
        if not shutil.which("nvidia-smi"):
            return {
                "available": False,
                "error": "nvidia-smi not found in PATH",
                "total_mb": 0.0,
                "used_mb": 0.0,
                "free_mb": 0.0,
                "percent_used": 0.0
            }
        
        try:
            cmd = ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,nounits,noheader"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=3)
            lines = res.stdout.strip().splitlines()
            if not lines:
                return {"available": False, "error": "No GPU output"}
            
            parts = [float(p.strip()) for p in lines[0].split(",")]
            total, used, free = parts[0], parts[1], parts[2]
            percent = round((used / total) * 100.0, 2) if total > 0 else 0.0
            
            return {
                "available": True,
                "total_mb": total,
                "used_mb": used,
                "free_mb": free,
                "percent_used": percent
            }
        except Exception as e:
            return {
                "available": False,
                "error": str(e),
                "total_mb": 0.0,
                "used_mb": 0.0,
                "free_mb": 0.0,
                "percent_used": 0.0
            }

    @classmethod
    def check_memory_headroom(cls, max_vram_mb: int = 7000, max_ram_mb: int = 13500) -> Dict[str, Any]:
        """Verifies current memory consumption against hardware limits."""
        ram = cls.get_system_ram_mb()
        gpu = cls.get_gpu_vram_mb()
        
        ram_ok = ram["used_mb"] <= max_ram_mb
        vram_ok = True
        if gpu["available"]:
            vram_ok = gpu["used_mb"] <= max_vram_mb
            
        warnings = []
        if not ram_ok:
            warnings.append(f"RAM usage ({ram['used_mb']} MB) exceeds ceiling of {max_ram_mb} MB")
        if not vram_ok:
            warnings.append(f"GPU VRAM usage ({gpu['used_mb']} MB) exceeds ceiling of {max_vram_mb} MB")
            
        return {
            "within_limits": ram_ok and vram_ok,
            "system_ram": ram,
            "gpu_vram": gpu,
            "warnings": warnings
        }


class InferenceTracker:
    """Tracks latency, TTFT, token count, and generation throughput."""
    
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.start_time: float = time.perf_counter()
        self.first_token_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.token_count: int = 0

    def record_first_token(self):
        """Records time when the very first token is emitted."""
        if self.first_token_time is None:
            self.first_token_time = time.perf_counter()

    def record_tokens(self, count: int = 1):
        """Increments token count."""
        self.token_count += count

    def finish(self) -> Dict[str, Any]:
        """Calculates final latency and throughput metrics."""
        self.end_time = time.perf_counter()
        total_duration_sec = self.end_time - self.start_time
        
        ttft_ms = 0.0
        if self.first_token_time:
            ttft_ms = (self.first_token_time - self.start_time) * 1000.0
        else:
            ttft_ms = total_duration_sec * 1000.0

        throughput_tok_per_sec = 0.0
        if total_duration_sec > 0 and self.token_count > 0:
            throughput_tok_per_sec = self.token_count / total_duration_sec
            
        return {
            "model_name": self.model_name,
            "total_duration_ms": round(total_duration_sec * 1000.0, 2),
            "ttft_ms": round(ttft_ms, 2),
            "token_count": self.token_count,
            "throughput_tok_per_sec": round(throughput_tok_per_sec, 2)
        }
