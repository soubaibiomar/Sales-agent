"""
Model Gateway Unit & Contract Tests.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 39, 49, 63, 65-67; SAI-09, SAI-12)
"""
import pytest
from src.ai.model_gateway import ModelGateway, ModelGatewayRequest, PIIFilter
from src.ai.providers.base import BaseModelProvider


class MockFailingProvider(BaseModelProvider):
    async def generate(self, prompt, system_prompt=None, model=None, max_tokens=1024, temperature=0.2, timeout=5):
        raise TimeoutError("Simulated primary provider timeout.")
    async def stream(self, *args, **kwargs):
        raise NotImplementedError()
    async def embed(self, texts, model=None):
        return [[0.0] * 768 for _ in texts]
    async def rerank(self, query, documents, top_k=5, model=None):
        return []
    async def unload(self, model: str):
        return True


class MockSuccessProvider(BaseModelProvider):
    async def generate(self, prompt, system_prompt=None, model=None, max_tokens=1024, temperature=0.2, timeout=5):
        return {
            "content": f"Verified answer for: {prompt[:30]}",
            "model": model or "qwen3.5:4b",
            "metrics": {"ttft_ms": 45.0, "total_duration_ms": 150.0}
        }
    async def stream(self, *args, **kwargs):
        raise NotImplementedError()
    async def embed(self, texts, model=None):
        return [[0.1] * 768 for _ in texts]
    async def rerank(self, query, documents, top_k=5, model=None):
        return []
    async def unload(self, model: str):
        return True


@pytest.mark.asyncio
async def test_pii_redaction_moroccan_cin_and_cc():
    """Validates redaction of Moroccan CIN, Luhn-valid Credit Cards, phone and email."""
    # Moroccan CIN: BK654321, Luhn CC: 4532 0150 1234 5671, Phone: 0661123456, Email: test@acme.ma
    raw_prompt = (
        "Client CIN est BK654321, email: contact@client.ma, tel: 0661123456, "
        "carte bancaire: 4532 0150 1234 5671."
    )
    sanitized, count = PIIFilter.redact(raw_prompt)

    assert count >= 4
    assert "BK654321" not in sanitized
    assert "[REDACTED_CIN]" in sanitized
    assert "contact@client.ma" not in sanitized
    assert "[REDACTED_EMAIL]" in sanitized
    assert "0661123456" not in sanitized
    assert "[REDACTED_PHONE]" in sanitized
    assert "4532 0150 1234 5671" not in sanitized
    assert "[REDACTED_CREDIT_CARD]" in sanitized


@pytest.mark.asyncio
async def test_model_gateway_happy_path():
    """Validates primary provider execution and token accounting."""
    gateway = ModelGateway(
        local_provider=MockSuccessProvider(),
        fallback_provider=MockSuccessProvider()
    )
    req = ModelGatewayRequest(
        tenant_id="tenant-test-1",
        prompt="Quel est le prix du kit solaire ?",
        model="qwen3.5:4b",
        max_latency_ms=3000.0
    )
    res = await gateway.generate(req)

    assert res.status == "SUCCESS"
    assert res.provider == "ollama"
    assert "Verified answer" in res.content
    assert res.prompt_tokens > 0
    assert res.completion_tokens > 0
    assert res.latency_ms > 0


@pytest.mark.asyncio
async def test_model_gateway_fallback_simulation():
    """Validates seamless fallback to secondary provider when primary fails."""
    gateway = ModelGateway(
        local_provider=MockFailingProvider(),
        fallback_provider=MockSuccessProvider()
    )
    req = ModelGatewayRequest(
        tenant_id="tenant-test-1",
        prompt="Demande de cotation urgente",
        model="qwen3.5:4b",
        allow_fallback=True
    )
    res = await gateway.generate(req)

    assert res.status == "FALLBACK"
    assert res.provider == "fallback_cloud"
    assert "Primary failed" in (res.error_message or "")
    assert "Verified answer" in res.content


@pytest.mark.asyncio
async def test_model_gateway_health_telemetry():
    """Validates health check telemetry report."""
    gateway = ModelGateway()
    health = await gateway.get_health()

    assert health["status"] == "HEALTHY"
    assert "gpu_vram_used_mb" in health
    assert "gpu_vram_headroom_mb" in health
    assert "primary_llm" in health
