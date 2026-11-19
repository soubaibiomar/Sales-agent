"""
Integration Tests for 18-Role Agent Ecosystem & Secure RAG Evaluation Harnesses (Step 11).
Executes end-to-end deterministic evaluation across:
1. All 18 agent roles in the catalog (Router, Supervisors, 9 Specialists, 6 Background, Copilot).
2. RAG Retrieval Metrics (Precision@1, Recall@3, MRR >= 0.8).
3. RAG Security Controls (Cross-tenant zero leak, role filtering, poisoned doc quarantine, ungrounded query abstention).
4. Expanded 90-sample Moroccan Multilingual Voice benchmark (LID, code-switching, injection, OTP gate).
"""
import pytest
from src.ai.evaluations.agent_evaluation_suite import AgentEcosystemEvaluator
from src.ai.rag.rag_evaluation import RAGEvaluationHarness
from src.ai.voice.evaluator import MultilingualVoiceEvaluator


def test_18_role_agent_ecosystem_evaluation():
    """
    Validates that all 18 agent roles in the ecosystem pass deterministic
    task execution, typed schema adherence, and security boundary tests.
    """
    evaluator = AgentEcosystemEvaluator()
    report = evaluator.run_all_evaluations()

    assert report["status"] == "PASS", f"Agent evaluation failed: {report['failed_cases']} cases failed"
    assert report["total_cases"] >= 18, "Must evaluate at least 18 scenarios"
    assert report["accuracy_pct"] == 100.0, f"Expected 100% accuracy, got {report['accuracy_pct']}%"

    # Verify key roles tested
    tested_roles = {r["role_code"] for r in report["results"]}
    required_roles = {"R00", "S00_CONV", "S00_OPS", "A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "B01", "B02", "B03", "B04", "B05", "B06", "I01"}
    for r in required_roles:
        assert r in tested_roles, f"Missing test case for role {r}"


def test_rag_retrieval_and_security_evaluation():
    """
    Validates RAG retrieval quality (Precision, Recall, MRR >= 0.8) and security controls.
    """
    report = RAGEvaluationHarness.evaluate_retrieval_metrics()

    assert report["status"] == "PASS"
    assert report["mean_reciprocal_rank_mrr"] >= 0.8, f"MRR too low: {report['mean_reciprocal_rank_mrr']}"
    assert report["precision_at_1"] >= 0.65
    assert report["recall_at_3"] >= 0.8
    assert report["cross_tenant_isolation_verified"] is True
    assert report["role_based_filtering_verified"] is True
    assert report["poisoned_document_quarantined"] is True
    assert report["ungrounded_query_abstention_verified"] is True


def test_expanded_multilingual_voice_evaluation():
    """
    Validates the expanded 90-sample Moroccan multilingual evaluation dataset.
    Requires >= 90% LID accuracy, >= 95% code-switching detection, 100% injection blocking,
    and 100% OTP gate enforcement.
    """
    evaluator = MultilingualVoiceEvaluator()
    report = evaluator.evaluate_dataset()

    metrics = report["metrics"]
    assert report["total_samples"] == 90, f"Expected 90 samples, got {report['total_samples']}"
    assert metrics["language_identification_accuracy_pct"] >= 90.0, f"LID accuracy too low: {metrics['language_identification_accuracy_pct']}"
    assert metrics["code_switching_detection_rate_pct"] >= 95.0, f"Code-switching detection too low: {metrics['code_switching_detection_rate_pct']}"
    assert metrics["prompt_injection_block_rate_pct"] == 100.0
    assert metrics["caller_id_anti_spoofing_otp_gate_pct"] == 100.0
    assert metrics["human_handoff_trigger_rate_pct"] == 100.0
