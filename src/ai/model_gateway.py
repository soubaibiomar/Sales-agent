"""
Model Gateway Service.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 39-40, 49, 63, 65-67; SAI-06 to SAI-10, SAI-12; ADR-008)

Provides:
1. Configurable local/cloud model routing with VRAM mutual exclusion.
2. Latency and token budget enforcement with automated fallback.
3. Server-side PII sanitization (Credit cards, Moroccan CIN, email, phone).
4. Token accounting and versioned model execution ledger logging.
5. Provider health, concurrency limits and telemetry.
"""
import re
import time
import uuid
import hashlib
import logging
from typing import Dict, Any, Optional, List, Tuple
from pydantic import BaseModel, Field

from src.ai.config import ai_config
from src.ai.providers.base import BaseModelProvider
from src.ai.providers.ollama_provider import OllamaProvider
from src.ai.providers.cloud_provider import CloudProvider
from src.ai.model_lifecycle import lifecycle_manager, VRAMMutualExclusionError
from src.ai.resource_monitor import HardwareTelemetry

logger = logging.getLogger("SalesAI.ModelGateway")


class PIIFilter:
    """
    Detects and sanitizes PII from prompts and model completions.
    Covers Moroccan CIN (Carte d'Identité Nationale), Credit Cards, Phone numbers, Emails.
    """
    # Moroccan CIN: 1 or 2 uppercase letters followed by 5 or 6 digits (e.g., AB123456, BK654321)
    CIN_PATTERN = re.compile(r'\b[A-Za-z]{1,2}[0-9]{5,6}\b')
    # Credit cards: 13-19 digits, possibly hyphen or space separated
    CC_PATTERN = re.compile(r'\b(?:\d[ -]*?){13,19}\b')
    # Email
    EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    # Moroccan Phone Numbers (+212 or 06/07/05)
    PHONE_PATTERN = re.compile(r'(?:\+212|0)[ \-]?[5-7][0-9]{8}\b')

    @classmethod
    def _is_luhn_valid(cls, card_number: str) -> bool:
        digits = [int(c) for c in card_number if c.isdigit()]
        if len(digits) < 13 or len(digits) > 19:
            return False
        checksum = 0
        reverse_digits = digits[::-1]
        for i, digit in enumerate(reverse_digits):
            if i % 2 == 1:
                doubled = digit * 2
                checksum += doubled - 9 if doubled > 9 else doubled
            else:
                checksum += digit
        return checksum % 10 == 0

    @classmethod
    def redact(cls, text: str) -> Tuple[str, int]:
        if not text:
            return text, 0
        redaction_count = 0

        # 1. Credit Cards with Luhn validation
        def cc_repl(match):
            nonlocal redaction_count
            raw = match.group(0)
            if cls._is_luhn_valid(raw):
                redaction_count += 1
                return "[REDACTED_CREDIT_CARD]"
            return raw

        sanitized = cls.CC_PATTERN.sub(cc_repl, text)

        # 2. Moroccan CIN
        def cin_repl(match):
            nonlocal redaction_count
            redaction_count += 1
            return "[REDACTED_CIN]"

        sanitized = cls.CIN_PATTERN.sub(cin_repl, sanitized)

        # 3. Email
        def email_repl(match):
            nonlocal redaction_count
            redaction_count += 1
            return "[REDACTED_EMAIL]"

        sanitized = cls.EMAIL_PATTERN.sub(email_repl, sanitized)

        # 4. Phone
        def phone_repl(match):
            nonlocal redaction_count
            redaction_count += 1
            return "[REDACTED_PHONE]"

        sanitized = cls.PHONE_PATTERN.sub(phone_repl, sanitized)

        return sanitized, redaction_count


class ModelGatewayRequest(BaseModel):
    tenant_id: str
    prompt: str
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    turn_id: Optional[str] = None
    conversation_id: Optional[str] = None
    prompt_template_id: Optional[str] = None
    max_tokens: int = 1024
    temperature: float = 0.2
    # Explicit latency budget in ms. None = provider timeouts sized from measured cold
    # starts (F-16); a 5 s default made every cold start fail.
    max_latency_ms: Optional[float] = None
    allow_fallback: bool = True
    enforce_pii_redaction: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModelGatewayResponse(BaseModel):
    content: str
    provider: str
    model: str
    turn_id: Optional[str] = None
    latency_ms: float
    ttft_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    pii_redacted_count: int
    status: str  # SUCCESS, FALLBACK, BLOCKED, ERROR
    error_message: Optional[str] = None

    @property
    def text(self) -> str:
        return self.content


class ModelGateway:
    """
    Central Model Gateway orchestrating LLM inference with hardware guardrails,
    budgets, PII filtering, and audit ledger persistence.
    """
    def __init__(
        self,
        local_provider: Optional[BaseModelProvider] = None,
        fallback_provider: Optional[BaseModelProvider] = None
    ):
        self.local_provider = local_provider or OllamaProvider()
        self.fallback_provider = fallback_provider or CloudProvider(provider_name="gemini_fallback")
        self.cost_per_1k_tokens = {
            "qwen3.5:4b": 0.0,  # Local hardware: $0.0
            "qwen3.5:9b-q4_K_M": 0.0,
            "gemini-1.5-flash": 0.00015,
            "default": 0.0002
        }

    async def get_health(self) -> Dict[str, Any]:
        """Returns health telemetry, memory headroom and active models."""
        ram = HardwareTelemetry.get_system_ram_mb()
        gpu = HardwareTelemetry.get_gpu_vram_mb()
        ram_used = ram.get("used_mb", 0.0)
        gpu_used = gpu.get("used_mb", 0.0)
        return {
            "status": "HEALTHY",
            "active_gpu_model": lifecycle_manager.active_gpu_model,
            "primary_llm": ai_config.primary_llm,
            "reasoning_llm": ai_config.reasoning_llm,
            "gpu_vram_used_mb": gpu_used,
            "gpu_vram_headroom_mb": max(0.0, ai_config.max_gpu_vram_mb - gpu_used),
            "system_ram_used_mb": ram_used,
            "system_ram_headroom_mb": max(0.0, ai_config.max_system_ram_mb - ram_used),
            "inference_mode": ai_config.inference_mode
        }

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        # Approx 1 token per 4 chars or whitespace split
        return max(1, len(text.split()) * 4 // 3)

    def _calculate_cost(self, model: str, total_tokens: int) -> float:
        rate = self.cost_per_1k_tokens.get(model, self.cost_per_1k_tokens["default"])
        return round((total_tokens / 1000.0) * rate, 6)

    async def generate(self, req: ModelGatewayRequest, db_session=None) -> ModelGatewayResponse:
        """
        Executes bounded inference request with latency/cost budgets, PII filtering,
        and fallback guarantees.
        """
        start_time = time.time()
        turn_id = req.turn_id or str(uuid.uuid4())
        prompt_hash = hashlib.sha256(req.prompt.encode("utf-8")).hexdigest()

        # Step 1: PII Sanitization
        sanitized_prompt = req.prompt
        pii_count = 0
        if req.enforce_pii_redaction:
            sanitized_prompt, pii_count = PIIFilter.redact(req.prompt)

        target_model = req.model or ai_config.primary_llm
        provider_name = "ollama"
        result_content = ""
        ttft_ms = 0.0
        status = "SUCCESS"
        error_msg = None

        # Step 2: Primary local execution
        try:
            # Latency budget timeout in seconds
            timeout_sec = max(1.0, req.max_latency_ms / 1000.0) if req.max_latency_ms else None
            gen_res = await self.local_provider.generate(
                prompt=sanitized_prompt,
                system_prompt=req.system_prompt,
                model=target_model,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                timeout=timeout_sec
            )
            result_content = gen_res.get("content", "")
            metrics = gen_res.get("metrics", {})
            ttft_ms = metrics.get("ttft_ms", 0.0)
            target_model = gen_res.get("model", target_model)

        except Exception as e:
            logger.warning(f"Primary provider generation failed: {e}")
            if not req.allow_fallback:
                latency_ms = (time.time() - start_time) * 1000.0
                return ModelGatewayResponse(
                    content="",
                    provider=provider_name,
                    model=target_model,
                    turn_id=turn_id,
                    latency_ms=latency_ms,
                    ttft_ms=0.0,
                    prompt_tokens=self._estimate_tokens(sanitized_prompt),
                    completion_tokens=0,
                    total_tokens=self._estimate_tokens(sanitized_prompt),
                    estimated_cost_usd=0.0,
                    pii_redacted_count=pii_count,
                    status="ERROR",
                    error_message=str(e)
                )

            # Step 3: Graceful fallback
            logger.info("Failing over to fallback provider...")
            provider_name = "fallback_cloud"
            status = "FALLBACK"
            error_msg = f"Primary failed: {str(e)}"
            try:
                fallback_res = await self.fallback_provider.generate(
                    prompt=sanitized_prompt,
                    system_prompt=req.system_prompt,
                    max_tokens=req.max_tokens,
                    temperature=req.temperature
                )
                result_content = fallback_res.get("content", "")
                metrics = fallback_res.get("metrics", {})
                ttft_ms = metrics.get("ttft_ms", 120.0)
                target_model = fallback_res.get("model", "cloud-fallback")
            except Exception as fe:
                logger.error(f"Fallback provider also failed: {fe}")
                # Honest degradation (F-16): no fabricated answer; hand the turn to a human.
                result_content = "Désolé, le service d'assistance est momentanément indisponible. Un conseiller humain va vous répondre."
                status = "UNAVAILABLE_HANDOFF"
                error_msg = f"Fallback error: {str(fe)}"

        # Step 4: Output PII filter on generated text
        if req.enforce_pii_redaction and result_content:
            result_content, out_pii = PIIFilter.redact(result_content)
            pii_count += out_pii

        end_time = time.time()
        latency_ms = round((end_time - start_time) * 1000.0, 2)
        prompt_tokens = self._estimate_tokens(sanitized_prompt)
        completion_tokens = self._estimate_tokens(result_content)
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = self._calculate_cost(target_model, total_tokens)

        # Step 5: Persist ModelExecutionLog if db_session provided
        if db_session:
            try:
                from src.backend.models.entities import ModelExecutionLog
                log_entry = ModelExecutionLog(
                    id=str(uuid.uuid4()),
                    tenant_id=req.tenant_id,
                    turn_id=turn_id,
                    conversation_id=req.conversation_id,
                    provider=provider_name,
                    model_name=target_model,
                    prompt_template_id=req.prompt_template_id,
                    prompt_hash=prompt_hash,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    estimated_cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    ttft_ms=ttft_ms,
                    pii_redacted_count=pii_count,
                    status=status,
                    error_message=error_msg,
                    metadata_json=req.metadata
                )
                db_session.add(log_entry)
                await db_session.flush()
            except Exception as log_err:
                logger.warning(f"Failed to record model execution log: {log_err}")

        return ModelGatewayResponse(
            content=result_content,
            provider=provider_name,
            model=target_model,
            turn_id=turn_id,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost_usd,
            pii_redacted_count=pii_count,
            status=status,
            error_message=error_msg
        )


# Global singleton instance
model_gateway = ModelGateway()
