"""
AI Model Observability & Runtime Telemetry Tracker.
Instruments Model Gateway turns, token consumption, latency distributions (TTFT, tok/s),
and tracks GPU VRAM / Host RAM footprint with cold vs. warm lifecycle tagging.
(Controls 39-40, 63-64, 66; Invariant 9)
"""
import time
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from src.ai.resource_monitor import HardwareTelemetry
from src.ai.model_lifecycle import ModelLifecycleManager

logger = logging.getLogger("SalesAI.ModelObservability")


class ModelExecutionProfile:
    """Represents the rich telemetry record of a single LLM reasoning turn."""
    def __init__(
        self,
        trace_id: str,
        tenant_id: str,
        agent_role: str,
        model_name: str,
        model_tier: str,
        is_cold_start: bool,
        prompt_tokens: int,
        completion_tokens: int,
        ttft_ms: float,
        generation_duration_ms: float,
        total_latency_ms: float,
        throughput_tok_per_s: float,
        context_utilization_pct: float,
        lease_wait_ms: float,
        routing_reason: str,
        status: str = "SUCCESS",
        error_category: Optional[str] = None
    ):
        self.trace_id = trace_id
        self.tenant_id = tenant_id
        self.agent_role = agent_role
        self.model_name = model_name
        self.model_tier = model_tier
        self.is_cold_start = is_cold_start
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.ttft_ms = round(ttft_ms, 2)
        self.generation_duration_ms = round(generation_duration_ms, 2)
        self.total_latency_ms = round(total_latency_ms, 2)
        self.throughput_tok_per_s = round(throughput_tok_per_s, 2)
        self.context_utilization_pct = round(context_utilization_pct, 2)
        self.lease_wait_ms = round(lease_wait_ms, 2)
        self.routing_reason = routing_reason
        self.status = status
        self.error_category = error_category
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "agent_role": self.agent_role,
            "model_name": self.model_name,
            "model_tier": self.model_tier,
            "is_cold_start": self.is_cold_start,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "ttft_ms": self.ttft_ms,
            "generation_duration_ms": self.generation_duration_ms,
            "total_latency_ms": self.total_latency_ms,
            "throughput_tok_per_s": self.throughput_tok_per_s,
            "context_utilization_pct": self.context_utilization_pct,
            "lease_wait_ms": self.lease_wait_ms,
            "routing_reason": self.routing_reason,
            "status": self.status,
            "error_category": self.error_category,
            "timestamp": self.timestamp
        }


class ModelObservabilityTracker:
    """Singleton in-memory telemetry buffer and metric aggregator for Model Gateway turns."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelObservabilityTracker, cls).__new__(cls)
            cls._instance._profiles = []
            cls._instance._warm_models = set()
        return cls._instance

    def record_turn_execution(
        self,
        trace_id: str,
        tenant_id: str,
        agent_role: str,
        model_name: str,
        model_tier: str,
        prompt_tokens: int,
        completion_tokens: int,
        ttft_ms: float,
        generation_duration_ms: float,
        total_latency_ms: float,
        context_window_limit: int = 4096,
        lease_wait_ms: float = 0.0,
        routing_reason: str = "PRIMARY_DEFAULT",
        status: str = "SUCCESS",
        error_category: Optional[str] = None
    ) -> ModelExecutionProfile:
        """Records a completed LLM inference turn."""
        is_cold = model_name not in self._warm_models
        self._warm_models.add(model_name)

        gen_seconds = generation_duration_ms / 1000.0
        tok_s = (completion_tokens / gen_seconds) if gen_seconds > 0 else 0.0
        ctx_pct = ((prompt_tokens + completion_tokens) / context_window_limit) * 100.0 if context_window_limit > 0 else 0.0

        profile = ModelExecutionProfile(
            trace_id=trace_id,
            tenant_id=tenant_id,
            agent_role=agent_role,
            model_name=model_name,
            model_tier=model_tier,
            is_cold_start=is_cold,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            ttft_ms=ttft_ms,
            generation_duration_ms=generation_duration_ms,
            total_latency_ms=total_latency_ms,
            throughput_tok_per_s=tok_s,
            context_utilization_pct=ctx_pct,
            lease_wait_ms=lease_wait_ms,
            routing_reason=routing_reason,
            status=status,
            error_category=error_category
        )

        self._profiles.append(profile)
        if len(self._profiles) > 1000:
            self._profiles.pop(0)

        return profile

    def get_aggregated_model_metrics(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Calculates aggregated performance statistics for the AI operations console."""
        profiles = [p for p in self._profiles if tenant_id is None or p.tenant_id == tenant_id]
        if not profiles:
            return {
                "total_inferences": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "avg_ttft_ms": 0.0,
                "p95_ttft_ms": 0.0,
                "avg_throughput_tok_s": 0.0,
                "avg_latency_ms": 0.0,
                "error_rate_pct": 0.0,
                "cold_starts_count": 0,
                "recent_executions": []
            }

        total_prompt = sum(p.prompt_tokens for p in profiles)
        total_comp = sum(p.completion_tokens for p in profiles)
        ttfts = [p.ttft_ms for p in profiles]
        ttfts_sorted = sorted(ttfts)
        p95_ttft = ttfts_sorted[int(len(ttfts_sorted) * 0.95)] if ttfts else 0.0
        avg_tok_s = sum(p.throughput_tok_per_s for p in profiles) / len(profiles)
        avg_lat = sum(p.total_latency_ms for p in profiles) / len(profiles)
        errors = [p for p in profiles if p.status != "SUCCESS"]
        cold_starts = sum(1 for p in profiles if p.is_cold_start)

        return {
            "total_inferences": len(profiles),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_comp,
            "total_tokens": total_prompt + total_comp,
            "avg_ttft_ms": round(sum(ttfts) / len(ttfts), 2),
            "p95_ttft_ms": round(p95_ttft, 2),
            "avg_throughput_tok_s": round(avg_tok_s, 2),
            "avg_latency_ms": round(avg_lat, 2),
            "error_rate_pct": round(len(errors) / len(profiles) * 100.0, 2),
            "cold_starts_count": cold_starts,
            "recent_executions": [p.to_dict() for p in reversed(profiles[-25:])]
        }
