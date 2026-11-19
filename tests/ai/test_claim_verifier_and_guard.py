"""
Claim-Level Verifier & Output Guard Tests.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 65, 66, 67; Invariants 2, 8)
"""
import pytest
from src.ai.output_guard import ClaimVerifier, OutputGuard, EvidenceEnvelope


def test_claim_verifier_grounded_price():
    """Validates that candidate text quoting verified prices passes."""
    envelope = EvidenceEnvelope(
        tenant_id="tenant-acme",
        verified_prices={"SKU-SOLAR-01": 1250.0},
        verified_currency="MAD"
    )
    candidate_text = "Le kit panneau solaire 400W est au prix vérifié de 1250 MAD TTC."
    is_valid, violations = ClaimVerifier.verify(candidate_text, envelope)

    assert is_valid is True
    assert len(violations) == 0


def test_claim_verifier_ungrounded_price_rejection():
    """Validates that candidate text fabricating a lower or different price is caught."""
    envelope = EvidenceEnvelope(
        tenant_id="tenant-acme",
        verified_prices={"SKU-SOLAR-01": 1250.0},
        verified_currency="MAD"
    )
    # Model hallucinates a price of 600 MAD
    hallucinated_text = "Je peux vous proposer le kit solaire à seulement 600 MAD !"
    is_valid, violations = ClaimVerifier.verify(hallucinated_text, envelope)

    assert is_valid is False
    assert len(violations) == 1
    assert violations[0].violation_type == "UNGROUNDED_PRICE"
    assert "600" in violations[0].claim_text


def test_claim_verifier_unauthorized_discount_rejection():
    """Validates that unauthorized discount percentages are intercepted."""
    envelope = EvidenceEnvelope(
        tenant_id="tenant-acme",
        verified_prices={"SKU-SOLAR-01": 1250.0},
        approved_discounts_percent=[10.0]  # Only 10% approved
    )
    # Model promises 25% discount
    unauthorized_text = "Profitez d'une remise de 25% exceptionnelle sur votre commande."
    is_valid, violations = ClaimVerifier.verify(unauthorized_text, envelope)

    assert is_valid is False
    assert any(v.violation_type == "UNAUTHORIZED_DISCOUNT" for v in violations)


def test_claim_verifier_unverified_stock_rejection():
    """Validates that stock availability claims exceeding verified ATP are flagged."""
    envelope = EvidenceEnvelope(
        tenant_id="tenant-acme",
        verified_stock_atp={"SKU-SOLAR-01": 5}  # Only 5 in stock
    )
    # Model claims 20 in stock
    exaggerated_stock = "Nous avons 20 unités disponibles en stock immédiatement."
    is_valid, violations = ClaimVerifier.verify(exaggerated_stock, envelope)

    assert is_valid is False
    assert violations[0].violation_type == "UNVERIFIED_STOCK"


def test_output_guard_pii_redaction_and_ai_disclosure():
    """Validates end-to-end OutputGuard: PII scrubbing on valid text and AI disclosure."""
    envelope = EvidenceEnvelope(
        tenant_id="tenant-acme",
        verified_prices={"SKU-SOLAR-01": 1250.0},
        verified_currency="MAD"
    )
    # Valid grounded text with valid Luhn card
    raw_response = "Votre carte 4532 0150 1234 5671 est enregistrée. Le prix est de 1250 MAD."
    result = OutputGuard.inspect_and_guard(raw_response, evidence=envelope, include_disclosure=True)

    # 1. PII should be redacted
    assert "4532 0150 1234 5671" not in result.sanitized_text
    assert "[REDACTED_CREDIT_CARD]" in result.sanitized_text
    assert result.pii_redacted_count >= 1

    # 2. Grounded price should remain safe
    assert result.is_safe is True
    assert "1250 MAD" in result.sanitized_text

    # 3. AI disclosure notice should be appended
    assert result.ai_disclosure_added is True
    assert "Assistant IA Commercial" in result.sanitized_text


def test_output_guard_ungrounded_fallback():
    """Validates that ungrounded commercial claims trigger grounded fallback message."""
    envelope = EvidenceEnvelope(
        tenant_id="tenant-acme",
        verified_prices={"SKU-SOLAR-01": 1250.0},
        verified_currency="MAD"
    )
    raw_response = "Le prix est de 400 MAD."
    result = OutputGuard.inspect_and_guard(raw_response, evidence=envelope, include_disclosure=True)

    assert result.is_safe is False
    assert len(result.violations) == 1
    assert "1250.0 MAD" in result.sanitized_text
