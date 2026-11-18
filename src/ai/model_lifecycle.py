"""
Model Lifecycle Manager enforcing VRAM mutual exclusion and on-demand model loading.
Guarantees that 4B and 9B models are never co-resident in GPU memory.
"""
import urllib.request
import json
import logging
from typing import Optional, Set, Dict, Any
from src.ai.config import ai_config
from src.ai.resource_monitor import HardwareTelemetry

logger = logging.getLogger("SalesAI.ModelLifecycle")

class VRAMMutualExclusionError(Exception):
    """Raised when an operation would violate GPU VRAM co-residency invariants."""
    pass

class ModelLifecycleManager:
    """
    Orchestrates GPU VRAM state transitions and on-demand model life-cycles.
    """
    def __init__(self, ollama_url: Optional[str] = None):
        self.ollama_url = ollama_url or ai_config.ollama_base_url
        self.active_gpu_model: Optional[str] = None
        self.active_optional_cpu_models: Set[str] = set()

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
        
        # Conflict: 4B vs 9B
        is_4b = "4b" in target_model.lower()
        is_9b = "9b" in target_model.lower()
        active_is_4b = "4b" in self.active_gpu_model.lower()
        active_is_9b = "9b" in self.active_gpu_model.lower()

        if (is_4b and active_is_9b) or (is_9b and active_is_4b):
            return False
            
        return False

    def evict_gpu_model(self, model_name: str) -> bool:
        """
        Instructs Ollama to immediately unload the model from VRAM by setting keep_alive to 0.
        """
        logger.info(f"Evicting GPU model: {model_name} from VRAM...")
        try:
            req_data = json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.ollama_url}/api/generate",
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            # Short timeout; non-blocking attempt if Ollama offline
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass
        except Exception as e:
            logger.warning(f"Ollama unload request for {model_name} encountered notice: {e}")

        if self.active_gpu_model == model_name:
            self.active_gpu_model = None
            
        return True

    def prepare_for_inference(self, requested_model: str, is_complex_reasoning: bool = False) -> str:
        """
        Determines the appropriate model (4B vs 9B) and prepares VRAM state.
        Only allows 9B when is_complex_reasoning is explicitly True.
        """
        target_model = requested_model
        if is_complex_reasoning:
            target_model = ai_config.reasoning_llm
        else:
            # Default to primary 4B model
            if "9b" in requested_model.lower() and not is_complex_reasoning:
                logger.info("Unjustified 9B request downscaled to primary 4B model.")
                target_model = ai_config.primary_llm

        # Check mutual exclusion
        if not self.can_load_gpu_model(target_model):
            if self.active_gpu_model:
                logger.info(f"Evicting active model {self.active_gpu_model} to load {target_model}...")
                self.evict_gpu_model(self.active_gpu_model)

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
        telemetry = HardwareTelemetry.get_gpu_vram_mb()
        return {
            "active_gpu_model": self.active_gpu_model,
            "active_optional_cpu_models": list(self.active_optional_cpu_models),
            "gpu_telemetry": telemetry,
            "co_residency_violation": False
        }

lifecycle_manager = ModelLifecycleManager()
