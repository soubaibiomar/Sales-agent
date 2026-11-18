"""
Procurement & Multi-Warehouse Pydantic Schemas.
Suppliers, Supplier Catalogs, RFQs, Purchase Orders, Goods Receipts, and Stock Transfers.
Step 06: Sprint 3 - Operate
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# 1. Suppliers
class SupplierCreate(BaseModel):
    supplier_code: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    contact_name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    payment_terms: str = Field("NET_30", max_length=100)
    currency: str = Field("MAD", max_length=10)
    address_json: Optional[Dict[str, Any]] = Field(default_factory=dict)


class SupplierUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    payment_terms: Optional[str] = None
    currency: Optional[str] = None
    address_json: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    supplier_code: str
    name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    payment_terms: str
    currency: str
    address_json: Dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


# 2. Supplier Product Catalog
class SupplierProductCreate(BaseModel):
    product_id: str
    sku: str = Field(..., min_length=1, max_length=100)
    supplier_sku: Optional[str] = Field(None, max_length=100)
    unit_cost_cents: int = Field(..., ge=0)
    currency: str = Field("MAD", max_length=10)
    lead_time_days: int = Field(7, ge=0)
    min_order_quantity: int = Field(1, ge=1)


class SupplierProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    supplier_id: str
    product_id: str
    sku: str
    supplier_sku: Optional[str] = None
    unit_cost_cents: int
    currency: str
    lead_time_days: int
    min_order_quantity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# 3. Request For Quotation (RFQ)
class RFQItemRequest(BaseModel):
    product_id: Optional[str] = None
    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    quantity: int = Field(..., ge=1)
    target_unit_cost_cents: Optional[int] = Field(None, ge=0)


class RFQCreateRequest(BaseModel):
    supplier_id: str
    deadline_date: Optional[datetime] = None
    notes: Optional[str] = None
    items: List[RFQItemRequest] = Field(..., min_length=1)


class RFQItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    rfq_id: str
    product_id: Optional[str] = None
    sku: str
    name: str
    quantity: int
    target_unit_cost_cents: Optional[int] = None
    quoted_unit_cost_cents: Optional[int] = None
    created_at: datetime


class RFQResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    rfq_number: str
    supplier_id: str
    status: str
    deadline_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_by_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[RFQItemResponse] = Field(default_factory=list)


# 4. Purchase Orders (PO)
class POItemRequest(BaseModel):
    product_id: Optional[str] = None
    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    quantity_ordered: int = Field(..., ge=1)
    unit_cost_cents: int = Field(..., ge=0)


class PurchaseOrderCreateRequest(BaseModel):
    supplier_id: str
    warehouse_id: str
    rfq_id: Optional[str] = None
    currency: str = Field("MAD", max_length=10)
    payment_terms: str = Field("NET_30", max_length=100)
    notes: Optional[str] = None
    expected_delivery_date: Optional[datetime] = None
    items: List[POItemRequest] = Field(..., min_length=1)


class POItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    purchase_order_id: str
    product_id: Optional[str] = None
    sku: str
    name: str
    quantity_ordered: int
    quantity_received: int
    unit_cost_cents: int
    subtotal_cents: int
    created_at: datetime


class PurchaseOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    po_number: str
    supplier_id: str
    warehouse_id: str
    rfq_id: Optional[str] = None
    status: str
    version: int
    currency: str
    subtotal_cents: int
    tax_cents: int
    grand_total_cents: int
    payment_terms: str
    notes: Optional[str] = None
    approved_by_user_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    issued_at: Optional[datetime] = None
    expected_delivery_date: Optional[datetime] = None
    created_by_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[POItemResponse] = Field(default_factory=list)


# 5. Goods Receipts (GRN)
class GoodsReceiptItemRequest(BaseModel):
    po_item_id: str
    sku: str
    quantity_received: int = Field(..., ge=0)
    quantity_rejected: int = Field(0, ge=0)
    rejection_reason: Optional[str] = None
    lot_number: Optional[str] = None


class GoodsReceiptCreateRequest(BaseModel):
    purchase_order_id: str
    warehouse_id: str
    carrier_name: Optional[str] = None
    tracking_reference: Optional[str] = None
    notes: Optional[str] = None
    items: List[GoodsReceiptItemRequest] = Field(..., min_length=1)


class GoodsReceiptItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    goods_receipt_id: str
    po_item_id: str
    sku: str
    quantity_received: int
    quantity_rejected: int
    rejection_reason: Optional[str] = None
    lot_number: Optional[str] = None
    created_at: datetime


class GoodsReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    receipt_number: str
    purchase_order_id: str
    warehouse_id: str
    received_by_user_id: Optional[str] = None
    carrier_name: Optional[str] = None
    tracking_reference: Optional[str] = None
    notes: Optional[str] = None
    received_at: datetime
    created_at: datetime
    items: List[GoodsReceiptItemResponse] = Field(default_factory=list)


# 6. Stock Transfers
class StockTransferItemRequest(BaseModel):
    sku: str
    quantity_requested: int = Field(..., ge=1)


class StockTransferCreateRequest(BaseModel):
    source_warehouse_id: str
    destination_warehouse_id: str
    notes: Optional[str] = None
    items: List[StockTransferItemRequest] = Field(..., min_length=1)


class StockTransferItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    transfer_id: str
    sku: str
    quantity_requested: int
    quantity_shipped: int
    quantity_received: int
    created_at: datetime


class StockTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    transfer_number: str
    source_warehouse_id: str
    destination_warehouse_id: str
    status: str
    notes: Optional[str] = None
    created_by_user_id: Optional[str] = None
    shipped_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    items: List[StockTransferItemResponse] = Field(default_factory=list)
