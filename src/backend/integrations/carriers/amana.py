"""
Amana Express (Poste Maroc / Barid Al-Maghrib) Carrier Adapter.
Domestic and regional logistics provider for Morocco.
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


class AmanaCarrierAdapter(CarrierAdapter):
    """Adapter for Amana Express (Barid Al-Maghrib domestic Moroccan parcel carrier)."""

    def __init__(self, api_key: Optional[str] = None, webhook_secret: Optional[str] = None):
        self.api_key = api_key or "amana_test_key_morocco"
        self.webhook_secret = webhook_secret or "amana_webhook_secret_default"

    @property
    def carrier_code(self) -> str:
        return "AMANA"

    async def get_rate_quotes(
        self,
        origin_address: Dict[str, Any],
        destination_address: Dict[str, Any],
        weight_grams: int,
        dimensions_cm: Optional[Dict[str, float]] = None
    ) -> List[CarrierRateQuote]:
        # Moroccan domestic tiered pricing
        weight_kg = max(1, (weight_grams + 999) // 1000)
        # Base standard express: 35 MAD (3500 cents) for first kg + 5 MAD (500 cents) per extra kg
        standard_cents = 3500 + max(0, weight_kg - 1) * 500
        # Priority next-day: 50 MAD (5000 cents) base + 8 MAD (800 cents) per extra kg
        express_cents = 5000 + max(0, weight_kg - 1) * 800

        return [
            CarrierRateQuote(
                carrier_code="AMANA",
                carrier_service="AMANA_EXPRESS_NATIONAL",
                cost_cents=standard_cents,
                currency="MAD",
                estimated_transit_days=2,
                guaranteed=False,
                metadata={"network": "national_road", "weight_kg": weight_kg}
            ),
            CarrierRateQuote(
                carrier_code="AMANA",
                carrier_service="AMANA_EXPRESS_PRIORITY",
                cost_cents=express_cents,
                currency="MAD",
                estimated_transit_days=1,
                guaranteed=True,
                metadata={"network": "priority_air_road", "weight_kg": weight_kg}
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
        # Generate Amana barcode format: MA + 9 digits + AMN
        unique_suffix = abs(hash(f"{shipment_number}:{uuid.uuid4()}")) % 1000000000
        tracking_number = f"MA{unique_suffix:09d}AMN"
        label_url = f"https://api.amana.ma/v2/labels/{tracking_number}.pdf"
        estimated_delivery = datetime.now(timezone.utc) + timedelta(days=2)

        return CarrierShipmentResult(
            tracking_number=tracking_number,
            shipping_label_url=label_url,
            carrier_code="AMANA",
            carrier_service="AMANA_EXPRESS_NATIONAL",
            estimated_delivery_at=estimated_delivery,
            raw_response={
                "provider": "Amana Barid Al-Maghrib",
                "tracking_number": tracking_number,
                "status": "MANIFEST_REGISTERED",
                "label_format": "PDF_4X6"
            }
        )

    async def fetch_tracking(self, tracking_number: str) -> List[CarrierTrackingEvent]:
        # Emits simulated initial events for newly registered tracking numbers
        now = datetime.now(timezone.utc)
        return [
            CarrierTrackingEvent(
                status="SHIPPED",
                event_timestamp=now - timedelta(hours=4),
                location="Hub National Casablanca Nouaceur",
                description="Colis déposé au centre de tri Amana",
                raw_payload={"carrier_status": "COLLECTED"}
            ),
            CarrierTrackingEvent(
                status="IN_TRANSIT",
                event_timestamp=now - timedelta(hours=1),
                location="En transit vers agence de distribution",
                description="Acheminement vers centre régional",
                raw_payload={"carrier_status": "TRANSIT"}
            )
        ]

    def verify_webhook_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str
    ) -> bool:
        sig_header = headers.get("X-Amana-Signature") or headers.get("x-amana-signature")
        if not sig_header:
            return False
        computed = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig_header.lower().strip(), computed.lower().strip())

    def parse_tracking_webhook(
        self,
        headers: Dict[str, str],
        payload: Dict[str, Any]
    ) -> List[CarrierTrackingEvent]:
        raw_status = str(payload.get("event_type") or payload.get("status") or "").upper().strip()
        timestamp_str = payload.get("timestamp")
        if timestamp_str:
            try:
                event_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except Exception:
                event_time = datetime.now(timezone.utc)
        else:
            event_time = datetime.now(timezone.utc)

        # Map Amana status codes to platform canonical statuses
        status_map = {
            "MANIFEST_REGISTERED": "CREATED",
            "COLLECTED": "SHIPPED",
            "ACCEPTED": "SHIPPED",
            "TRANSIT": "IN_TRANSIT",
            "SORTING": "IN_TRANSIT",
            "OUT_FOR_DELIVERY": "OUT_FOR_DELIVERY",
            "DELIVERED": "DELIVERED",
            "DELIVERY_FAILED": "FAILED",
            "RETURN_TO_SENDER": "RETURNED",
            "CANCELLED": "CANCELLED"
        }
        canonical_status = status_map.get(raw_status, "IN_TRANSIT")

        return [
            CarrierTrackingEvent(
                status=canonical_status,
                event_timestamp=event_time,
                location=payload.get("location") or "Maroc",
                description=payload.get("description") or f"Amana update: {raw_status}",
                raw_payload=payload
            )
        ]
