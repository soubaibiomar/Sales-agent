"""
Language, Intent, Risk Router & Conversation Supervisor.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 39, 40, 65, 67; SAI-06 to SAI-10)

Enforces:
1. Multilingual identification (fr-FR, en-US, ar-MA, ary-Arab, ary-Latn).
2. Intent classification and confidence scoring.
3. Three execution classes (DIRECT_SAFE_READ, BOUNDED_REASONING_TURN, DURABLE_WORKFLOW).
4. Adversarial prompt injection risk gating (fail-closed).
5. Single conversation supervisor with human takeover silencing and stale-turn fencing.
"""
import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from pydantic import BaseModel, Field

from src.ai.rag.poison_detector import PoisonDetector

logger = logging.getLogger("SalesAI.Router")


class RoutingDecision(BaseModel):
    language: str  # fr-FR, en-US, ar-MA, ary-Arab, ary-Latn
    intent: str
    confidence: float
    execution_class: str  # DIRECT_SAFE_READ, BOUNDED_REASONING_TURN, DURABLE_WORKFLOW
    target_specialist: Optional[str] = None
    risk_level: str  # LOW, MEDIUM, HIGH
    is_adversarial: bool = False
    adversarial_reason: Optional[str] = None
    action: str = "EXECUTE"  # EXECUTE, SILENCE_HUMAN_TAKEOVER, ESCALATE_HUMAN, REJECT_ADVERSARIAL


class ConversationRouter:
    """
    Analyzes inbound customer utterances to classify language, intent,
    execution class, and adversarial risk.
    """

    # Arabizi regex patterns (numbers 3=ayn, 7=ha, 9=qaf, 5=kha)
    ARABIZI_NUMERALS = re.compile(r'\b[a-zA-Z]*[3795][a-zA-Z]*\b')
    ARABIZI_KEYWORDS = {
        "salam", "khoya", "khti", "bghit", "dyal", "dyalkom", "chhal", "kifach",
        "fin", "chno", "fayn", "wakha", "mezian", "daba", "ghadi", "3afak", "tbarkellah"
    }

    # Arabic script characters
    ARABIC_CHAR_PATTERN = re.compile(r'[\u0600-\u06FF]')

    # French markers
    FRENCH_KEYWORDS = {
        "bonjour", "bonsoir", "merci", "prix", "produit", "catalogue", "commande",
        "livraison", "combien", "devis", "remise", "facture", "garantie", "disponible"
    }

    # English markers
    ENGLISH_KEYWORDS = {
        "hello", "hi", "price", "pricing", "quote", "catalog", "order", "shipping",
        "how", "much", "discount", "invoice", "warranty", "available", "support",
        "could", "would", "please", "energy", "storage", "solar", "need", "want"
    }

    @classmethod
    def detect_language(cls, text: str) -> str:
        """
        Detects primary language and dialect:
        - ary-Arab: Moroccan Arabic in Arabic script
        - ar-MA: Modern Standard Arabic
        - ary-Latn: Moroccan Darija in Latin script (Arabizi)
        - fr-FR: French
        - en-US: English
        """
        if not text:
            return "fr-FR"

        # Check for Arabic script
        arabic_matches = cls.ARABIC_CHAR_PATTERN.findall(text)
        if len(arabic_matches) > len(text.replace(" ", "")) * 0.3:
            # Moroccan Darija dialect vocabulary in Arabic script
            darija_arabic_words = {
                "واخا", "شحال", "فين", "ديال", "بغيت", "كيداير", "دابا",
                "عفاك", "بزاف", "واش", "كاين", "هاد", "ديالي", "ديالكم"
            }
            tokens = set(re.findall(r'[\u0600-\u06FF]+', text))
            if tokens & darija_arabic_words:
                return "ary-Arab"
            return "ar-MA"

        # Check for Arabizi (Latin script Darija)
        lower_tokens = set(re.findall(r'\b[a-zA-Z0-9_-]+\b', text.lower()))
        has_arabizi_words = bool(lower_tokens & cls.ARABIZI_KEYWORDS)
        has_arabizi_numerals = bool(cls.ARABIZI_NUMERALS.search(text))
        if has_arabizi_words or has_arabizi_numerals:
            return "ary-Latn"

        # Check for French vs English
        french_matches = len(lower_tokens & cls.FRENCH_KEYWORDS)
        english_matches = len(lower_tokens & cls.ENGLISH_KEYWORDS)

        if french_matches >= english_matches and french_matches > 0:
            return "fr-FR"
        elif english_matches > french_matches:
            return "en-US"

        # Default standard Moroccan business language: French
        return "fr-FR"

    @classmethod
    def classify_intent(cls, text: str) -> Tuple[str, float]:
        """Classifies intent and confidence."""
        lower = text.lower()

        # Greetings
        if any(w in lower for w in ["salam", "bonjour", "bonsoir", "hello", "hi", "salut", "marhaba", "مرحبا"]):
            if len(lower.split()) <= 3:
                return "GREETING", 0.95

        # Order tracking & status
        if any(w in lower for w in ["suivi", "commande", "tracking", "status", "mon colis", "fin wsslat", "فين وصلات"]):
            return "ORDER_INQUIRY", 0.90

        # Pricing & Quotes
        if any(w in lower for w in ["devis", "prix", "chhal", "combien", "quote", "cost", "tarif", "remise", "discount", "شحال الثمن"]):
            return "PRICING_QUOTE", 0.88

        # Inventory ATP
        if any(w in lower for w in ["stock", "disponible", "dispo", "available", "wash kayn", "واش كاين"]):
            return "INVENTORY_ATP", 0.85

        # Catalog Browsing
        if any(w in lower for w in ["catalogue", "produit", "produits", "products", "catalog", "list", "شنو عندكم"]):
            return "CATALOG_QUERY", 0.85

        # Support & Warranty
        if any(w in lower for w in ["probleme", "panne", "garantie", "reclamation", "defectueux", "rma", "support", "مشكل"]):
            return "SUPPORT_ISSUE", 0.85

        # Appointment scheduling
        if any(w in lower for w in ["rendez-vous", "rdv", "reunion", "meeting", "rendezvous", "موعد"]):
            return "SCHEDULE_APPOINTMENT", 0.85

        # Human takeover request
        if any(w in lower for w in ["humain", "conseiller", "agent", "human", "bghit nhedar m3a", "بغيت نهضر مع انسان"]):
            return "HUMAN_TAKEOVER", 0.95

        return "CATALOG_QUERY", 0.60

    @classmethod
    def route(
        cls,
        text: str,
        turn_id: Optional[str] = None,
        is_human_owned: bool = False
    ) -> RoutingDecision:
        """
        Executes end-to-end routing decision: language, intent, execution class,
        adversarial risk and supervisor actions.
        """
        # Step 1: Detect adversarial prompt injection (fail-closed)
        is_poisoned, poison_reason = PoisonDetector.scan(text)
        if is_poisoned:
            logger.warning(f"Adversarial attack intercepted by router: {poison_reason}")
            return RoutingDecision(
                language=cls.detect_language(text),
                intent="ADVERSARIAL_ATTACK",
                confidence=1.0,
                execution_class="DIRECT_SAFE_READ",
                risk_level="HIGH",
                is_adversarial=True,
                adversarial_reason=poison_reason,
                action="REJECT_ADVERSARIAL"
            )

        # Step 2: Language & Intent
        lang = cls.detect_language(text)
        intent, conf = cls.classify_intent(text)

        # Step 3: Human Takeover Fencing (Invariant: Human ownership silences autonomous responses)
        if is_human_owned or intent == "HUMAN_TAKEOVER":
            return RoutingDecision(
                language=lang,
                intent="HUMAN_TAKEOVER",
                confidence=conf,
                execution_class="DIRECT_SAFE_READ",
                target_specialist=None,
                risk_level="LOW",
                action="SILENCE_HUMAN_TAKEOVER"
            )

        # Step 4: Map to Execution Class
        # Class 1: DIRECT_SAFE_READ (Safe reads, FAQ, Tracking lookup by code)
        if intent in ["GREETING", "INVENTORY_ATP"]:
            exec_class = "DIRECT_SAFE_READ"
            specialist = "product_specialist"
        # Class 3: DURABLE_WORKFLOW (Checkout, Escalations, POs, High-consequence)
        elif intent in ["SCHEDULE_APPOINTMENT"]:
            exec_class = "DURABLE_WORKFLOW"
            specialist = "appointment_specialist"
        # Class 2: BOUNDED_REASONING_TURN (Interactive reasoning within schema)
        elif intent == "PRICING_QUOTE":
            exec_class = "BOUNDED_REASONING_TURN"
            specialist = "pricing_specialist"
        elif intent == "ORDER_INQUIRY":
            exec_class = "DIRECT_SAFE_READ"
            specialist = "order_specialist"
        elif intent == "SUPPORT_ISSUE":
            exec_class = "BOUNDED_REASONING_TURN"
            specialist = "support_specialist"
        else:
            exec_class = "BOUNDED_REASONING_TURN"
            specialist = "product_specialist"

        return RoutingDecision(
            language=lang,
            intent=intent,
            confidence=conf,
            execution_class=exec_class,
            target_specialist=specialist,
            risk_level="LOW",
            action="EXECUTE"
        )


class ConversationSupervisor:
    """
    Enforces conversation turn lifecycle, single conversation ownership,
    and stale-turn fencing against concurrency races.
    """
    def __init__(self):
        # In-memory turn tracking per conversation {conversation_id: expected_turn_version}
        self._turn_versions: Dict[str, int] = {}
        # Human ownership tracker {conversation_id: human_user_id}
        self._human_owners: Dict[str, str] = {}

    def set_human_takeover(self, conversation_id: str, human_user_id: str):
        """Designates a human rep as sole owner of this conversation, silencing AI."""
        self._human_owners[conversation_id] = human_user_id

    def release_human_takeover(self, conversation_id: str):
        """Releases human ownership, allowing AI autonomy to resume."""
        self._human_owners.pop(conversation_id, None)

    def is_human_owned(self, conversation_id: str) -> bool:
        return conversation_id in self._human_owners

    def validate_and_advance_turn(
        self,
        conversation_id: str,
        expected_turn_version: int
    ) -> Tuple[bool, int]:
        """
        Validates that expected_turn_version matches the current turn.
        If matched, increments turn version and returns (True, new_version).
        If mismatched, rejects turn as stale (False, current_version).
        """
        current_version = self._turn_versions.get(conversation_id, 0)
        if expected_turn_version != current_version:
            logger.warning(
                f"Stale turn detected for conversation {conversation_id}: "
                f"expected {expected_turn_version}, current {current_version}"
            )
            return False, current_version

        new_version = current_version + 1
        self._turn_versions[conversation_id] = new_version
        return True, new_version
