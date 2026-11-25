"""
Model Lifecycle Manager enforcing VRAM mutual exclusion and on-demand model loading.
Guarantees that 4B and 9B models are never co-resident in GPU memory.
Now with cross-process file-locking and live voice call safety guards.
"""
import os
import tempfile
import httpx
import json
import logging
import threading
import time
from typing import Optional, Set, Dict, Any, List
from contextlib import contextmanager
from filelock import FileLock, Timeout
from src.ai.config import ai_config
from src.ai.resource_monitor import HardwareTelemetry

logger = logging.getLogger("SalesAI.ModelLifecycle")

class VRAMMutualExclusionError(Exception):
    """Raised when an operation would violate GPU VRAM co-residency invariants or eviction fails."""
    pass

class VRAMEvictionConflictError(VRAMMutualExclusionError):
    """Raised when eviction or model switching is attempted while active generation leases exist."""
    pass

class VoiceModelSafetyError(Exception):
    """Raised when 9B reasoning model is erroneously requested synchronously during a live voice call."""
    pass

class ModelLifecycleManager:
    """
    Orchestrates GPU VRAM state transitions and on-demand model life-cycles.
    Thread-safe and cross-process safe via FileLock and fail-closed.
    Features active generation lease tracking to prevent eviction during token generation.
    """
    def __init__(self, ollama_url: Optional[str] = None, lock_path: Optional[str] = None):
        self.ollama_url = ollama_url or ai_config.ollama_base_url
        self.active_gpu_model: Optional[str] = None
        self.active_optional_cpu_models: Set[str] = set()
        self._thread_lock = threading.RLock()
        self._local_leases: Dict[str, int] = {}
        
        lock_dir = os.environ.get("SALES_AI_LOCK_DIR") or tempfile.gettempdir()
        lock_file = lock_path or os.path.join(lock_dir, "sales_ai_ollama_vram.lock")
        self._file_lock = FileLock(lock_file, timeout=20.0)
        self._lease_file = os.path.join(lock_dir, "sales_ai_inference_leases.json")

    @contextmanager
    def _with_file_lock(self):
        """Context manager that safely permits re-entrant file lock acquisition in the same process."""
        if self._file_lock.is_locked:
            yield
        else:
            with self._file_lock:
                yield

    def _read_cross_process_leases(self) -> Dict[str, List[Dict[str, Any]]]:
        """Reads lease file and filters out expired leases (> 60s timeout)."""
        if not os.path.exists(self._lease_file):
            return {}
        try:
            with open(self._lease_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            valid: Dict[str, List[Dict[str, Any]]] = {}
            for model, leases in data.items():
                active = [l for l in leases if (now - l.get("ts", 0)) < 60.0]
                if active:
                    valid[model] = active
            return valid
        except Exception as e:
            logger.debug(f"Could not read cross-process leases: {e}")
            return {}

    def _write_cross_process_leases(self, leases: Dict[str, List[Dict[str, Any]]]):
        try:
            tmp_path = f"{self._lease_file}.tmp.{os.getpid()}"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(leases, f)
            os.replace(tmp_path, self._lease_file)
        except Exception as e:
            logger.warning(f"Could not write cross-process leases: {e}")

    def acquire_inference_lease(self, model_name: str, lease_id: Optional[str] = None) -> str:
        """
        Acquires an active generation lease for model_name, both in-memory and cross-process.
        Prevents eviction of model_name while tokens are being generated.
        Returns a unique lease_id.
        """
        import uuid
        lid = lease_id or str(uuid.uuid4())
        with self._thread_lock:
            self._local_leases[model_name] = self._local_leases.get(model_name, 0) + 1
            try:
                with self._with_file_lock():
                    leases = self._read_cross_process_leases()
                    entry = {"id": lid, "pid": os.getpid(), "ts": time.time()}
                    leases.setdefault(model_name, []).append(entry)
                    self._write_cross_process_leases(leases)
            except Exception as e:
                logger.warning(f"Failed to record cross-process lease to file: {e}")
        logger.debug(f"Acquired generation lease {lid} for model {model_name}")
        return lid

    def release_inference_lease(self, model_name: str, lease_id: Optional[str] = None):
        """Releases active generation lease for model_name."""
        with self._thread_lock:
            if model_name in self._local_leases:
                self._local_leases[model_name] = max(0, self._local_leases[model_name] - 1)
            try:
                with self._with_file_lock():
                    leases = self._read_cross_process_leases()
                    if model_name in leases:
                        if lease_id:
                            leases[model_name] = [l for l in leases[model_name] if l.get("id") != lease_id]
                        elif leases[model_name]:
                            leases[model_name].pop()
                        if not leases[model_name]:
                            del leases[model_name]
                        self._write_cross_process_leases(leases)
            except Exception as e:
                logger.warning(f"Failed to release cross-process lease in file: {e}")
        logger.debug(f"Released generation lease for model {model_name}")

    def get_active_lease_count(self, model_name: str) -> int:
        """Returns total active generation leases for model across threads and processes."""
        with self._thread_lock:
            local_count = self._local_leases.get(model_name, 0)
            try:
                with self._with_file_lock():
                    leases = self._read_cross_process_leases()
                    xp_count = len(leases.get(model_name, []))
            except Exception:
                xp_count = 0
        return max(local_count, xp_count)

    @contextmanager
    def generation_lease(self, model_name: str):
        """Context manager to ensure generation lease is always safely released."""
        lid = self.acquire_inference_lease(model_name)
        try:
            yield lid
        finally:
            self.release_inference_lease(model_name, lid)

    def get_running_ollama_models(self) -> List[Dict[str, Any]]:
        """Queries /api/ps to inspect active models resident in memory."""
        try:
            resp = httpx.get(f"{self.ollama_url}/api/ps", timeout=3)
            resp.raise_for_status()
            return resp.json().get("models", [])
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

    def evict_gpu_model(self, model_name: str, verify: bool = True, force: bool = False) -> bool:
        """
        Instructs Ollama to immediately unload the model from VRAM by setting keep_alive to 0.
        Verifies model eviction from /api/ps to fail closed if eviction fails.
        Rejects eviction if active generation leases exist (unless force=True).
        """
        active_leases = self.get_active_lease_count(model_name)
        if active_leases > 0 and not force:
            msg = (
                f"Cannot evict model {model_name}: {active_leases} active generation lease(s) in flight. "
                "Eviction blocked to prevent terminating active token stream."
            )
            logger.error(msg)
            raise VRAMEvictionConflictError(msg)

        logger.info(f"Evicting GPU model: {model_name} from VRAM...")
        try:
            httpx.post(f"{self.ollama_url}/api/generate", json={"model": model_name, "keep_alive": 0}, timeout=5)
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
            with self._with_file_lock():
                target_model = requested_model
                if is_complex_reasoning:
                    target_model = ai_config.reasoning_llm
                else:
                    # Downscale unjustified 9B requests
                    if "9b" in requested_model.lower() and not is_complex_reasoning:
                        logger.info("Unjustified 9B request downscaled to primary 4B model.")
                        target_model = ai_config.primary_llm

                # Enforce mutual exclusion (F-27): decide from what Ollama ACTUALLY has
                # resident (/api/ps), not only from this process's memory, so a model
                # loaded by another worker or client is also evicted before switching.
                resident = {m.get("name") or m.get("model") for m in self.get_running_ollama_models()}
                if self.active_gpu_model:
                    resident.add(self.active_gpu_model)
                conflicting = sorted(
                    m for m in resident
                    if m and m != target_model and self._is_exclusive_llm(m) and self._is_exclusive_llm(target_model)
                )
                for model_name in conflicting:
                    active_leases = self.get_active_lease_count(model_name)
                    if active_leases > 0:
                        raise VRAMEvictionConflictError(
                            f"Cannot switch to {target_model}: resident model {model_name} "
                            f"has {active_leases} active generation lease(s) in flight."
                        )
                    logger.info(f"Evicting resident model {model_name} to load {target_model}...")
                    self.evict_gpu_model(model_name, verify=True)

                self.active_gpu_model = target_model
                return target_model

    @staticmethod
    def _is_exclusive_llm(model_name: str) -> bool:
        """The 4B and 9B generation models must never share the 8 GB GPU."""
        name = model_name.lower()
        primary, reasoning = ai_config.primary_llm.lower(), ai_config.reasoning_llm.lower()
        return name in (primary, reasoning) or name.startswith(primary.split(":")[0] + ":")

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
            "active_generation_leases": {
                ai_config.primary_llm: self.get_active_lease_count(ai_config.primary_llm),
                ai_config.reasoning_llm: self.get_active_lease_count(ai_config.reasoning_llm)
            },
            "gpu_telemetry": telemetry,
            "co_residency_violation": co_residency_violation
        }

lifecycle_manager = ModelLifecycleManager()
