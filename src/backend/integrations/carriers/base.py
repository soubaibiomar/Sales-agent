"""
Abstract Base Carrier Adapter & Normalized Carrier Event Data Contracts.
Step 06: Logistics & Carriers
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


@dataclass
class CarrierRateQuote:
    carrier_code: str
    carrier_service: str
    cost_cents: int
    currency: str = "MAD"
    estimated_transit_days: int = 2
    guaranteed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CarrierShipmentResult:
    tracking_number: str
    shipping_label_url: str
    carrier_code: str
    carrier_service: str
    estimated_delivery_at: Optional[datetime] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CarrierTrackingEvent:
    status: str  # CREATED, PICKING, PACKED, SHIPPED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, FAILED, RETURNED, CANCELLED
    event_timestamp: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class CarrierAdapter(ABC):
    """Abstract interface implemented by all carrier adapters."""

    @property
    @abstractmethod
    def carrier_code(self) -> str:
        """Normalized carrier code (e.g. AMANA, SIMULATED_EXPRESS, DHL, ARAMEX)."""
        pass

    @abstractmethod
    async def get_rate_quotes(
        self,
        origin_address: Dict[str, Any],
        destination_address: Dict[str, Any],
        weight_grams: int,
        dimensions_cm: Optional[Dict[str, float]] = None
    ) -> List[CarrierRateQuote]:
        """Calculates shipping rate options for the route and package size."""
        pass

    @abstractmethod
    async def book_shipment(
        self,
        shipment_number: str,
        origin_address: Dict[str, Any],
        destination_address: Dict[str, Any],
        delivery_contact: Dict[str, Any],
        items: List[Dict[str, Any]],
        weight_grams: int = 1000
    ) -> CarrierShipmentResult:
        """Books a shipment with the carrier, returning tracking number and label URL."""
        pass

    @abstractmethod
    async def fetch_tracking(self, tracking_number: str) -> List[CarrierTrackingEvent]:
        """Fetches normalized event history for a tracking number."""
        pass

    @abstractmethod
    def verify_webhook_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        secret: str
    ) -> bool:
        """Cryptographically verifies incoming webhook callback from the carrier."""
        pass

    @abstractmethod
    def parse_tracking_webhook(
        self,
        headers: Dict[str, str],
        payload: Dict[str, Any]
    ) -> List[CarrierTrackingEvent]:
        """Normalizes carrier webhook payload into standardized tracking events."""
        pass
