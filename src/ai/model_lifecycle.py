"""
Model Lifecycle Manager enforcing VRAM mutual exclusion and on-demand model loading.
Guarantees that 4B and 9B models are never co-resident in GPU memory.
Now with cross-process file-locking and live voice call safety guards.
"""
import os
import tempfile
import urllib.request
import json
import logging
import threading
import time
from typing import Optional, Set, Dict, Any, List
from filelock import FileLock, Timeout
from src.ai.config import ai_config
from src.ai.resource_monitor import HardwareTelemetry

logger = logging.getLogger("SalesAI.ModelLifecycle")

class VRAMMutualExclusionError(Exception):
    """Raised when an operation would violate GPU VRAM co-residency invariants or eviction fails."""
    pass

class VoiceModelSafetyError(Exception):
    """Raised when 9B reasoning model is erroneously requested synchronously during a live voice call."""
    pass

class ModelLifecycleManager:
    """
    Orchestrates GPU VRAM state transitions and on-demand model life-cycles.
    Thread-safe and cross-process safe via FileLock and fail-closed.
    """
    def __init__(self, ollama_url: Optional[str] = None, lock_path: Optional[str] = None):
        self.ollama_url = ollama_url or ai_config.ollama_base_url
        self.active_gpu_model: Optional[str] = None
        self.active_optional_cpu_models: Set[str] = set()
        self._thread_lock = threading.Lock()
        
        lock_file = lock_path or os.path.join(tempfile.gettempdir(), "sales_ai_ollama_vram.lock")
        self._file_lock = FileLock(lock_file, timeout=20.0)

    def get_running_ollama_models(self) -> List[Dict[str, Any]]:
        """Queries /api/ps to inspect active models resident in memory."""
        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/ps", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("models", [])
        except Exception as e:
            logger.debug(f"Could not connect to Ollama /api/ps: {e}")
            return []

    def can_load_gpu_model(self, target_model: str) -> bool:
        """
        Evaluates whether a model can be safely loaded into GPU VRAM.
        Invariants:
        1. 4B and 9B cannot be co-resident simultaneously.
        2. If active_gpu_model is set and different from target_model, eviction is required.
        """
        if self.active_gpu_model is None:
            return True
        if self.active_gpu_model == target_model:
            return True
        
        # Conflict check: 4B vs 9B
        is_4b = "4b" in target_model.lower()
        is_9b = "9b" in target_model.lower()
        active_is_4b = "4b" in self.active_gpu_model.lower()
        active_is_9b = "9b" in self.active_gpu_model.lower()

        if (is_4b and active_is_9b) or (is_9b and active_is_4b):
            return False
            
        return False

    def evict_gpu_model(self, model_name: str, verify: bool = True) -> bool:
        """
        Instructs Ollama to immediately unload the model from VRAM by setting keep_alive to 0.
        Verifies model eviction from /api/ps to fail closed if eviction fails.
        """
        logger.info(f"Evicting GPU model: {model_name} from VRAM...")
        try:
            req_data = json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.ollama_url}/api/generate",
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass
        except Exception as e:
            logger.warning(f"Ollama unload request for {model_name} encountered error: {e}")

        # Verification step
        if verify:
            time.sleep(0.5)
            running = self.get_running_ollama_models()
            still_resident = any(model_name in m.get("name", "") for m in running)
            if still_resident:
                msg = f"CRITICAL: Failed to evict {model_name}; model still resident in VRAM. Aborting transition to prevent GPU OOM."
                logger.error(msg)
                raise VRAMMutualExclusionError(msg)

        if self.active_gpu_model == model_name:
            self.active_gpu_model = None
            
        return True

    def prepare_for_inference(
        self,
        requested_model: str,
        is_complex_reasoning: bool = False,
        channel: Optional[str] = None
    ) -> str:
        """
        Thread-safe and cross-process safe preparation for inference turn.
        Enforces:
        1. Live voice call safety: 9B is prohibited synchronously during voice calls.
        2. 4B default; downscales unjustified 9B requests.
        3. Mutual exclusion: evicts resident model before loading conflicting model.
        """
        # Guard: Voice channel safety (Requirement 5)
        if channel == "voice":
            if "9b" in requested_model.lower() or is_complex_reasoning:
                raise VoiceModelSafetyError(
                    "Synchronous 9B invocation is strictly prohibited during live voice calls "
                    "to preserve target latency and avoid GPU VRAM switching stalls."
                )

        with self._thread_lock:
            with self._file_lock:
                target_model = requested_model
                if is_complex_reasoning:
                    target_model = ai_config.reasoning_llm
                else:
                    # Downscale unjustified 9B requests
                    if "9b" in requested_model.lower() and not is_complex_reasoning:
                        logger.info("Unjustified 9B request downscaled to primary 4B model.")
                        target_model = ai_config.primary_llm

                # Enforce mutual exclusion
                if not self.can_load_gpu_model(target_model):
                    if self.active_gpu_model:
                        logger.info(f"Evicting active model {self.active_gpu_model} to load {target_model}...")
                        self.evict_gpu_model(self.active_gpu_model, verify=True)

                self.active_gpu_model = target_model
                return target_model

    def load_optional_darija_tool(self, tool_name: str) -> bool:
        """Loads optional Moroccan Darija / Arabizi models into host RAM on demand."""
        allowed_tools = {
            ai_config.darija_lid,
            ai_config.arabizi_model,
            ai_config.darija_asr_candidate
        }
        if tool_name not in allowed_tools:
            logger.warning(f"Requested tool {tool_name} is not a recognized optional model.")
            return False

        logger.info(f"Loading optional Moroccan NLP tool on demand: {tool_name}")
        self.active_optional_cpu_models.add(tool_name)
        return True

    def unload_optional_tools(self):
        """Purges optional Moroccan NLP models from memory when turn finishes."""
        if self.active_optional_cpu_models:
            logger.info(f"Unloading optional CPU models: {self.active_optional_cpu_models}")
            self.active_optional_cpu_models.clear()

    def get_lifecycle_status(self) -> Dict[str, Any]:
        """Returns the current state of GPU and CPU models."""
        running_ollama = self.get_running_ollama_models()
        telemetry = HardwareTelemetry.get_gpu_vram_mb()
        
        # Check running models co-residency
        has_4b = any("4b" in m.get("name", "").lower() for m in running_ollama)
        has_9b = any("9b" in m.get("name", "").lower() for m in running_ollama)
        co_residency_violation = has_4b and has_9b

        return {
            "active_gpu_model": self.active_gpu_model,
            "running_in_ollama": [m.get("name") for m in running_ollama],
            "active_optional_cpu_models": list(self.active_optional_cpu_models),
            "gpu_telemetry": telemetry,
            "co_residency_violation": co_residency_violation
        }

lifecycle_manager = ModelLifecycleManager()
