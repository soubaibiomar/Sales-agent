"""
Simulated Express Carrier Adapter for Testing, CI, and Carrier Outage Scenarios.
(Controls 16, 21, 22, 57, 58)
Step 06: Logistics & Carriers
"""
import hmac
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from src.backend.integrations.carriers.base import (
    CarrierAdapter, CarrierRateQuote, CarrierShipmentResult, CarrierTrackingEvent
)


class SimulatedExpressCarrierAdapter(CarrierAdapter):
    """Deterministic simulated express carrier for integration and adversarial testing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        simulate_outage: bool = False
    ):
        self.api_key = api_key or "simulated_express_test_key"
        self.webhook_secret = webhook_secret or "simulated_webhook_secret_default"
        self.simulate_outage = simulate_outage

    @property
    def carrier_code(self) -> str:
        return "SIMULATED_EXPRESS"

    @staticmethod
    def compute_webhook_signature(raw_body: bytes, secret: str) -> str:
        """Helper for test suites to generate valid HMAC-SHA256 signatures."""
        return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    async def get_rate_quotes(
        self,
        origin_address: Dict[str, Any],
        destination_address: Dict[str, Any],
        weight_grams: int,
        dimensions_cm: Optional[Dict[str, float]] = None
    ) -> List[CarrierRateQuote]:
        if self.simulate_outage:
            raise RuntimeError("CarrierGatewayTimeout: Simulated carrier API is temporarily offline.")

        weight_kg = max(1, (weight_grams + 999) // 1000)
        return [
            CarrierRateQuote(
                carrier_code="SIMULATED_EXPRESS",
                carrier_service="EXPRESS_STANDARD",
                cost_cents=2500 + (weight_kg * 400),
                currency="MAD",
                estimated_transit_days=2,
                guaranteed=False,
                metadata={"network": "ground_express"}
            ),
            CarrierRateQuote(
                carrier_code="SIMULATED_EXPRESS",
                carrier_service="EXPRESS_NEXT_DAY",
                cost_cents=4500 + (weight_kg * 600),
                currency="MAD",
                estimated_transit_days=1,
                guaranteed=True,
                metadata={"network": "priority_air"}
            )
        ]

    async def book_shipment(
        self,
        shipment_number: str,
        origin_address: Dict[str, Any],
        destination_address: Dict[str, Any],
        delivery_contact: Dict[str, Any],
        items: List[Dict[str, Any]],
        weight_grams: int = 1000
    ) -> CarrierShipmentResult:
        if self.simulate_outage:
            raise RuntimeError("CarrierOutageError: Failed to connect to SimulatedExpress carrier booking API.")

        tracking_number = f"SIM-{uuid.uuid4().hex[:10].upper()}"
        label_url = f"https://labels.simulated-express.test/{tracking_number}.pdf"
        estimated_delivery = datetime.now(timezone.utc) + timedelta(days=2)

        return CarrierShipmentResult(
            tracking_number=tracking_number,
            shipping_label_url=label_url,
            carrier_code="SIMULATED_EXPRESS",
            carrier_service="EXPRESS_STANDARD",
            estimated_delivery_at=estimated_delivery,
            raw_response={
                "status": "BOOKED",
                "tracking_number": tracking_number,
                "label_url": label_url,
                "pieces": len(items)
            }
        )

    async def fetch_tracking(self, tracking_number: str) -> List[CarrierTrackingEvent]:
        if self.simulate_outage:
            raise RuntimeError("CarrierOutageError: Tracking endpoint unavailable.")

        now = datetime.now(timezone.utc)
        return [
            CarrierTrackingEvent(
                status="SHIPPED",
                event_timestamp=now - timedelta(hours=3),
                location="Logistics Hub - Depot 1",
                description="Package received by carrier",
                raw_payload={"step": "received"}
            ),
            CarrierTrackingEvent(
                status="IN_TRANSIT",
                event_timestamp=now - timedelta(hours=1),
                location="Regional Sort Center",
                description="In transit to destination facility",
                raw_payload={"step": "transit"}
            )
        ]

    def verify_webhook_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str
    ) -> bool:
        sig_header = (
            headers.get("X-Carrier-Signature") or
            headers.get("x-carrier-signature") or
            headers.get("X-Hub-Signature-256")
        )
        if not sig_header:
            return False
        expected = self.compute_webhook_signature(raw_body, secret)
        return hmac.compare_digest(sig_header.lower().strip(), expected.lower().strip())

    def parse_tracking_webhook(
        self,
        headers: Dict[str, str],
        payload: Dict[str, Any]
    ) -> List[CarrierTrackingEvent]:
        raw_status = str(payload.get("status") or payload.get("event") or "").upper().strip()
        ts_str = payload.get("event_timestamp") or payload.get("timestamp")
        if ts_str:
            try:
                event_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                event_time = datetime.now(timezone.utc)
        else:
            event_time = datetime.now(timezone.utc)

        status_mapping = {
            "MANIFEST": "CREATED",
            "PICKED_UP": "SHIPPED",
            "SHIPPED": "SHIPPED",
            "IN_TRANSIT": "IN_TRANSIT",
            "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
            "DELIVERED": "DELIVERED",
            "FAILED": "FAILED",
            "RETURNED": "RETURNED",
            "CANCELLED": "CANCELLED"
        }
        canonical_status = status_mapping.get(raw_status, "IN_TRANSIT")

        return [
            CarrierTrackingEvent(
                status=canonical_status,
                event_timestamp=event_time,
                location=payload.get("location") or "Distribution Center",
                description=payload.get("description") or f"Status: {canonical_status}",
                raw_payload=payload
            )
        ]
