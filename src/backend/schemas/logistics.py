"""
Logistics, Carriers, Fulfillment & Delivery Proof Pydantic Schemas.
Step 06: Sprint 3 - Operate
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class ShipmentItemRequest(BaseModel):
    order_item_id: str
    sku: str
    name: str
    quantity: int = Field(..., ge=1)


class ShipmentCreateRequest(BaseModel):
    order_id: str
    warehouse_id: str
    carrier_code: str = Field(..., max_length=50)  # AMANA, DHL, FEDEX, LOCAL_COURIER
    carrier_service: Optional[str] = Field("STANDARD", max_length=100)
    shipping_address_json: Dict[str, Any]
    delivery_contact_json: Dict[str, Any]
    items: List[ShipmentItemRequest] = Field(..., min_length=1)


class ShipmentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    shipment_id: str
    order_item_id: str
    sku: str
    name: str
    quantity: int
    created_at: datetime


class ShipmentTrackingEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    shipment_id: str
    status: str
    event_timestamp: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    raw_payload_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DeliveryProofResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    shipment_id: str
    recipient_name: str
    signature_image_url: Optional[str] = None
    photo_url: Optional[str] = None
    signed_at: datetime
    location_coordinates: Optional[str] = None
    created_at: datetime


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    shipment_number: str
    order_id: str
    warehouse_id: str
    carrier_code: str
    carrier_service: Optional[str] = None
    tracking_number: Optional[str] = None
    status: str
    shipping_address_json: Dict[str, Any]
    delivery_contact_json: Dict[str, Any]
    shipping_label_url: Optional[str] = None
    estimated_delivery_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    created_by_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[ShipmentItemResponse] = Field(default_factory=list)
    tracking_events: List[ShipmentTrackingEventResponse] = Field(default_factory=list)
    delivery_proof: Optional[DeliveryProofResponse] = None


class CarrierTrackingUpdateRequest(BaseModel):
    carrier_code: str
    tracking_number: str
    status: str  # IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, FAILED
    event_timestamp: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = Field(default_factory=dict)


class DeliveryProofCreateRequest(BaseModel):
    recipient_name: str = Field(..., min_length=1, max_length=255)
    signature_image_url: Optional[str] = Field(None, max_length=500)
    photo_url: Optional[str] = Field(None, max_length=500)
    location_coordinates: Optional[str] = Field(None, max_length=100)


class CarrierRateQuoteRequest(BaseModel):
    carrier_code: str
    warehouse_id: str
    destination_postal_code: str
    destination_city: str
    destination_country: str = "MA"
    weight_kg: float = Field(1.0, ge=0.1)


class CarrierRateQuoteResponse(BaseModel):
    carrier_code: str
    carrier_service: str
    currency: str
    shipping_cost_cents: int
    estimated_transit_days: int
