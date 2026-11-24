"""
Agent orchestration tests run against an explicit, deterministic model stub.

These tests verify routing, tool permissions, evidence handling, guards and audit
logging - not language-model quality. They previously depended on live Ollama output:
they "passed" only because the provider timed out after 5 s and returned fabricated
placeholder text (inspection finding F-16). Real model output is non-deterministic, so
asserting SUCCESS on it is not a reliable test. Model quality belongs in evaluations with
pinned models and held-out data, not in these unit tests.
"""
import pytest

from src.ai.model_gateway import model_gateway

# Claim-free reply: no price, stock, discount or payment assertion, so the outcome of
# each test depends on the orchestration code, not on what a model happened to say.
DETERMINISTIC_AGENT_REPLY = (
    "Demande bien reçue. Je prépare les éléments demandés ; tout montant, remise ou "
    "engagement devra recevoir l'approbation d'un responsable avant envoi au client."
)


class DeterministicAgentTestProvider:
    """Test double for the local LLM provider (labelled; never used outside tests)."""

    def __init__(self, reply: str = DETERMINISTIC_AGENT_REPLY):
        self.reply = reply
        self.calls = []

    async def generate(self, prompt, system_prompt=None, model=None, max_tokens=1024,
                       temperature=0.2, timeout=None, **kwargs):
        self.calls.append({"model": model, "prompt": prompt})
        return {"content": self.reply, "model": model or "qwen3.5:4b",
                "metrics": {"ttft_ms": 1.0, "total_duration_ms": 2.0, "token_count": len(self.reply.split())}}


@pytest.fixture(autouse=True)
def deterministic_agent_model(monkeypatch):
    provider = DeterministicAgentTestProvider()
    monkeypatch.setattr(model_gateway, "local_provider", provider)
    return provider
