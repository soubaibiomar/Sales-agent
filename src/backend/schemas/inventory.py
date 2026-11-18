"""
Pydantic schemas for Warehouse, Inventory Items, Reservations, and Movements.
Step 05: Sprint 3 - Transact
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class WarehouseCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    address_json: Optional[str] = "{}"
    is_active: bool = True


class WarehouseResponse(BaseModel):
    id: str
    tenant_id: str
    code: str
    name: str
    address_json: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InventoryItemCreateRequest(BaseModel):
    warehouse_id: str
    sku: str = Field(..., min_length=1, max_length=100)
    product_id: Optional[str] = None
    variant_id: Optional[str] = None
    initial_on_hand: int = Field(0, ge=0)
    backorder_allowed: bool = False


class InventoryItemAdjustRequest(BaseModel):
    quantity_delta: int = Field(..., description="Change in stock, positive or negative")
    movement_type: str = Field("ADJUSTMENT", description="INBOUND_RECEIPT, ADJUSTMENT, RETURN_RESTOCK, etc.")
    reference_type: str = Field("MANUAL_ADJUSTMENT")
    reference_id: str = Field("MANUAL")
    notes: Optional[str] = None


class InventoryItemResponse(BaseModel):
    id: str
    tenant_id: str
    warehouse_id: str
    product_id: Optional[str] = None
    variant_id: Optional[str] = None
    sku: str
    on_hand_quantity: int
    reserved_quantity: int
    allocated_quantity: int
    available_to_promise: int
    backorder_allowed: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockReservationRequest(BaseModel):
    sku: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    warehouse_id: Optional[str] = None
    order_id: Optional[str] = None
    quote_id: Optional[str] = None
    hold_duration_seconds: int = Field(1800, gt=0, le=86400, description="Default 30 minutes")
    idempotency_key: Optional[str] = None


class StockReservationResponse(BaseModel):
    id: str
    tenant_id: str
    inventory_item_id: str
    order_id: Optional[str] = None
    quote_id: Optional[str] = None
    sku: str
    quantity: int
    status: str
    reserved_until: datetime
    idempotency_key: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockMovementResponse(BaseModel):
    id: str
    tenant_id: str
    inventory_item_id: str
    movement_type: str
    quantity_delta: int
    previous_on_hand: int
    new_on_hand: int
    reference_type: str
    reference_id: str
    notes: Optional[str] = None
    created_by_user_id: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
