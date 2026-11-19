"""
Claim-Level Verifier and Output Semantic Guard.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 65, 66, 67; SAI-08, SAI-09; Invariants 2, 8)

Enforces:
1. Claim-level verification for prices, discounts, stock availability, and payment status.
2. Grounding against fresh deterministic domain evidence (EvidenceEnvelope).
3. PII masking and redaction on all outbound messages.
4. Statutory AI identity and recording disclosure (Control 65).
5. Hallucination suppression and automated clarification fallback.
"""
import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from pydantic import BaseModel, Field

from src.ai.model_gateway import PIIFilter
from src.ai.rag.poison_detector import PoisonDetector

PromptInjectionChecker = PoisonDetector

logger = logging.getLogger("SalesAI.OutputGuard")


class EvidenceEnvelope(BaseModel):
    """
    Structured domain ground truth provided to the turn from deterministic services.
    Only claims present in this envelope are considered grounded.
    """
    tenant_id: str = "system"
    verified_prices: Dict[str, float] = Field(default_factory=dict)  # {"SKU-01": 1250.0, "total": 1200.0}
    verified_currency: str = "MAD"
    verified_stock_atp: Dict[str, int] = Field(default_factory=dict)  # {"SKU-01": 15}
    approved_discounts_percent: List[float] = Field(default_factory=list)  # [10.0, 15.0]
    verified_order_status: Optional[str] = None  # "PAID", "CONFIRMED", "SHIPPED"
    verified_tracking_number: Optional[str] = None


class VerificationViolation(BaseModel):
    violation_type: str  # UNGROUNDED_PRICE, UNAUTHORIZED_DISCOUNT, UNVERIFIED_STOCK, UNVERIFIED_PAYMENT
    claim_text: str
    detail: str


class OutputGuardResult(BaseModel):
    is_safe: bool
    sanitized_text: str
    violations: List[VerificationViolation] = Field(default_factory=list)
    pii_redacted_count: int = 0
    ai_disclosure_added: bool = False

    @property
    def status(self) -> str:
        return "SAFE" if self.is_safe else "UNVERIFIED_CLAIMS_FALLBACK"


class ClaimVerifier:
    """
    Extracts customer-facing business claims (prices, discounts, stock, payment)
    and verifies each against the turn's EvidenceEnvelope.
    """

    # Price pattern: e.g. "1250 MAD", "1 250 DH", "450 Dhs", "50 EUR", "100 $"
    PRICE_PATTERN = re.compile(
        r'\b(?P<amount>\d+(?:[\s,.]\d{2,3})*(?:\.\d+)?)\s*(?P<curr>MAD|DH|DHS|EUR|USD|\$|€)\b',
        re.IGNORECASE
    )

    # Discount pattern: e.g. "20% de remise", "remise de 20%", "discount of 15%", "15% discount", "25% de réduction"
    DISCOUNT_PATTERN = re.compile(
        r'(?:(?:remise|discount|réduction|solde|تخفيض)\s*(?:de\s*)?(?P<pct1>\d{1,2})\s*%|(?P<pct2>\d{1,2})\s*%\s*(?:de\s*)?(?:remise|discount|réduction|solde|تخفيض))',
        re.IGNORECASE
    )

    # Stock availability assertions: e.g. "10 en stock", "disponible en stock", "rupture de stock"
    STOCK_CLAIM_PATTERN = re.compile(
        r'\b(?P<qty>\d+)\s*(?:unités?|pièces?|articles?)?\s*(?:en stock|disponibles?)\b',
        re.IGNORECASE
    )

    # Payment assertions: e.g. "votre commande est payée", "paiement validé", "payment confirmed"
    PAID_ASSERTION_PATTERN = re.compile(
        r'\b(?:commande|order)\s*(?:est|a été|has been)?\s*(?:payée?|validée?|confirmée?|paid|confirmed)\b',
        re.IGNORECASE
    )

    @classmethod
    def verify(cls, text: str, evidence: EvidenceEnvelope) -> Tuple[bool, List[VerificationViolation]]:
        """
        Scans text and returns (is_valid, list_of_violations).
        Fails if any factual commercial claim contradicts evidence.
        """
        violations: List[VerificationViolation] = []
        if not text:
            return True, violations

        # 1. Price claim verification
        for match in cls.PRICE_PATTERN.finditer(text):
            raw_amount_str = match.group("pct" if "pct" in match.groupdict() else "amount")
            # Normalize amount
            clean_str = raw_amount_str.replace(" ", "").replace(",", ".")
            try:
                claimed_amount = float(clean_str)
            except ValueError:
                continue

            # Check if claimed_amount is grounded in verified_prices
            grounded = False
            for v_price in evidence.verified_prices.values():
                if abs(claimed_amount - v_price) < 0.01:
                    grounded = True
                    break

            if not grounded:
                violations.append(
                    VerificationViolation(
                        violation_type="UNGROUNDED_PRICE",
                        claim_text=match.group(0),
                        detail=f"Claimed price {claimed_amount} is not grounded in verified prices: {evidence.verified_prices}"
                    )
                )

        # 2. Discount claim verification
        for match in cls.DISCOUNT_PATTERN.finditer(text):
            pct_str = match.group("pct1") or match.group("pct2")
            if not pct_str:
                continue
            try:
                claimed_pct = float(pct_str)
            except ValueError:
                continue

            if claimed_pct not in evidence.approved_discounts_percent and claimed_pct > 0:
                violations.append(
                    VerificationViolation(
                        violation_type="UNAUTHORIZED_DISCOUNT",
                        claim_text=match.group(0),
                        detail=f"Claimed discount {claimed_pct}% was not authorized by pricing domain service."
                    )
                )

        # 3. Stock claim verification
        for match in cls.STOCK_CLAIM_PATTERN.finditer(text):
            qty_str = match.group("qty")
            try:
                claimed_qty = int(qty_str)
            except ValueError:
                continue

            # Check if claimed_qty exceeds any verified stock
            exceeds = True
            for v_atp in evidence.verified_stock_atp.values():
                if claimed_qty <= v_atp:
                    exceeds = False
                    break

            if exceeds and evidence.verified_stock_atp:
                violations.append(
                    VerificationViolation(
                        violation_type="UNVERIFIED_STOCK",
                        claim_text=match.group(0),
                        detail=f"Claimed stock {claimed_qty} exceeds verified ATP: {evidence.verified_stock_atp}"
                    )
                )

        # 4. Payment status assertion verification
        if cls.PAID_ASSERTION_PATTERN.search(text):
            if evidence.verified_order_status != "PAID":
                violations.append(
                    VerificationViolation(
                        violation_type="UNVERIFIED_PAYMENT",
                        claim_text="Order claimed as paid/confirmed",
                        detail=f"Model asserted order is paid, but verified status is '{evidence.verified_order_status}'."
                    )
                )

        is_valid = len(violations) == 0
        return is_valid, violations

    @classmethod
    def verify_price_claim(cls, text: str, authorized_price_cents: int) -> Tuple[bool, str]:
        envelope = EvidenceEnvelope(
            tenant_id="eval",
            verified_prices={"item": authorized_price_cents / 100.0}
        )
        is_valid, violations = cls.verify(text, envelope)
        if not is_valid:
            reason = violations[0].detail if violations else "Ungrounded price claim"
            return False, reason
        return True, "Price claim grounded in verified domain records"


class OutputGuard:
    """
    Coordinates claim verification, PII redaction, and statutory AI disclosure
    on all candidate responses.
    """
    AI_DISCLOSURE_NOTICE = "\n\n🤖 [Assistant IA Commercial — Sales AI Management]"

    @classmethod
    def inspect_and_guard(
        cls,
        text: str,
        evidence: Optional[EvidenceEnvelope] = None,
        include_disclosure: bool = True
    ) -> OutputGuardResult:
        """
        Executes full guard pipeline:
        1. PII Redaction
        2. Claim Verification against EvidenceEnvelope
        3. Statutory AI Disclosure insertion
        """
        if not text:
            return OutputGuardResult(is_safe=True, sanitized_text="", violations=[])

        # Step 1: PII Redaction
        sanitized_text, pii_count = PIIFilter.redact(text)

        # Step 2: Claim Verification
        violations: List[VerificationViolation] = []
        if evidence:
            is_valid, violations = ClaimVerifier.verify(sanitized_text, evidence)
        else:
            is_valid = True

        # If commercial violations detected, synthesize safe grounded fallback
        if violations:
            logger.warning(f"OutputGuard detected {len(violations)} commercial claim violations: {violations}")
            is_safe = False
            # Fallback message referencing grounded facts
            grounded_prices = ", ".join(f"{k}: {v} {evidence.verified_currency}" for k, v in evidence.verified_prices.items()) if evidence else ""
            sanitized_text = (
                f"Voici les informations officielles vérifiées : {grounded_prices}. "
                "Pour toute remise ou condition spécifique, un devis officiel doit être émis par notre équipe commerciale."
            )
        else:
            is_safe = True

        # Step 3: Statutory AI Disclosure (Control 65)
        disclosure_added = False
        if include_disclosure and cls.AI_DISCLOSURE_NOTICE.strip() not in sanitized_text:
            sanitized_text += cls.AI_DISCLOSURE_NOTICE
            disclosure_added = True

        return OutputGuardResult(
            is_safe=is_safe,
            sanitized_text=sanitized_text,
            violations=violations,
            pii_redacted_count=pii_count,
            ai_disclosure_added=disclosure_added
        )
