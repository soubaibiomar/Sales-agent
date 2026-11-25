"""
Procurement & Multi-Warehouse Operations Domain Service.
Suppliers, Catalogs, RFQs, Purchase Orders, Over-Receipt Guards, Goods Receipts,
and Inter-Warehouse Stock Transfers.
(Controls 05, 06, 07, 16, 33, 34, 48, 57, 58)
Step 06: Sprint 3 - Operate
"""
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.models.entities import (
    Supplier, SupplierProduct, RFQ, RFQItem,
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem,
    StockTransfer, StockTransferItem, Warehouse, InventoryItem, StockMovement,
    AuditEvent
)
from src.backend.domains.inventory.service import InventoryService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProcurementError(Exception):
    pass


class SupplierNotFoundError(ProcurementError):
    pass


class RFQNotFoundError(ProcurementError):
    pass


class PurchaseOrderNotFoundError(ProcurementError):
    pass


class OverReceiptError(ProcurementError):
    pass


class InvalidPOStateTransitionError(ProcurementError):
    pass


class StockTransferNotFoundError(ProcurementError):
    pass


class InsufficientTransferStockError(ProcurementError):
    pass


# Concurrency lock for purchase order receipt serialization
_po_receipt_locks: Dict[str, asyncio.Lock] = {}
_transfer_ship_locks: Dict[str, asyncio.Lock] = {}

def get_transfer_ship_lock(key: str) -> asyncio.Lock:
    if key not in _transfer_ship_locks:
        _transfer_ship_locks[key] = asyncio.Lock()
    return _transfer_ship_locks[key]


class ProcurementService:
    def __init__(self, db: AsyncSession, inventory_service: Optional[InventoryService] = None):
        self.db = db
        self.inventory_service = inventory_service or InventoryService(db)

    # -------------------------------------------------------------------------
    # 1. SUPPLIERS REGISTRY
    # -------------------------------------------------------------------------
    async def create_supplier(
        self,
        tenant_id: str,
        supplier_code: str,
        name: str,
        contact_name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        payment_terms: str = "NET_30",
        currency: str = "MAD",
        address_json: Optional[Dict[str, Any]] = None
    ) -> Supplier:
        supplier = Supplier(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            supplier_code=supplier_code.upper().strip(),
            name=name.strip(),
            contact_name=contact_name,
            email=email,
            phone=phone,
            payment_terms=payment_terms,
            currency=currency.upper(),
            address_json=address_json or {},
            is_active=True
        )
        self.db.add(supplier)
        await self.db.flush()
        return supplier

    async def get_supplier(self, tenant_id: str, supplier_id: str) -> Optional[Supplier]:
        stmt = select(Supplier).where(
            and_(Supplier.tenant_id == tenant_id, Supplier.id == supplier_id)
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def list_suppliers(self, tenant_id: str, is_active: Optional[bool] = None, active_only: Optional[bool] = None,
                             limit: int = 50, offset: int = 0) -> List[Supplier]:
        # The API passes `active_only` (only filter when True); `is_active` keeps the old call style.
        if is_active is None and active_only:
            is_active = True
        stmt = select(Supplier).where(Supplier.tenant_id == tenant_id)
        if is_active is not None:
            stmt = stmt.where(Supplier.is_active == is_active)
        stmt = stmt.order_by(Supplier.name.asc()).limit(limit).offset(offset)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    # -------------------------------------------------------------------------
    # 2. SUPPLIER PRODUCT CATALOG
    # -------------------------------------------------------------------------
    async def add_supplier_product(
        self,
        tenant_id: str,
        supplier_id: str,
        product_id: str,
        sku: str,
        unit_cost_cents: int,
        supplier_sku: Optional[str] = None,
        currency: str = "MAD",
        lead_time_days: int = 7,
        min_order_quantity: int = 1
    ) -> SupplierProduct:
        sp = SupplierProduct(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            product_id=product_id,
            sku=sku.upper().strip(),
            supplier_sku=supplier_sku,
            unit_cost_cents=unit_cost_cents,
            currency=currency.upper(),
            lead_time_days=lead_time_days,
            min_order_quantity=min_order_quantity,
            is_active=True
        )
        self.db.add(sp)
        await self.db.flush()
        return sp

    async def list_supplier_products(self, tenant_id: str, supplier_id: str) -> List[SupplierProduct]:
        stmt = select(SupplierProduct).where(
            and_(SupplierProduct.tenant_id == tenant_id, SupplierProduct.supplier_id == supplier_id)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    # -------------------------------------------------------------------------
    # 3. REQUEST FOR QUOTATION (RFQ)
    # -------------------------------------------------------------------------
    async def create_rfq(
        self,
        tenant_id: str,
        supplier_id: str,
        items_data: List[Dict[str, Any]],
        deadline_date: Optional[datetime] = None,
        notes: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> RFQ:
        count_stmt = select(func.count()).select_from(RFQ).where(RFQ.tenant_id == tenant_id)
        res = await self.db.execute(count_stmt)
        seq = (res.scalar() or 0) + 1
        year = utc_now().year
        rfq_number = f"RFQ-{year}-{seq:05d}"

        rfq = RFQ(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            rfq_number=rfq_number,
            supplier_id=supplier_id,
            status="DRAFT",
            deadline_date=deadline_date,
            notes=notes,
            created_by_user_id=creator_id
        )
        self.db.add(rfq)
        await self.db.flush()

        for it in items_data:
            item = RFQItem(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                rfq_id=rfq.id,
                product_id=it.get("product_id"),
                sku=it["sku"].upper().strip(),
                name=it["name"],
                quantity=it["quantity"],
                target_unit_cost_cents=it.get("target_unit_cost_cents")
            )
            self.db.add(item)

        await self.db.flush()
        return await self.get_rfq(tenant_id, rfq.id)

    async def list_rfqs(self, tenant_id: str, status: Optional[str] = None, supplier_id: Optional[str] = None,
                        limit: int = 50, offset: int = 0) -> List[RFQ]:
        stmt = select(RFQ).options(selectinload(RFQ.items)).where(RFQ.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(RFQ.status == status)
        if supplier_id:
            stmt = stmt.where(RFQ.supplier_id == supplier_id)
        stmt = stmt.order_by(RFQ.created_at.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def send_rfq(self, tenant_id: str, rfq_id: str) -> RFQ:
        """DRAFT -> SENT. Sending twice is idempotent; closed/cancelled RFQs cannot be sent."""
        rfq = await self.get_rfq(tenant_id, rfq_id)
        if not rfq:
            raise RFQNotFoundError(f"RFQ {rfq_id} not found")
        if rfq.status in ("CLOSED", "CANCELLED"):
            raise ProcurementError(f"RFQ {rfq.rfq_number} is {rfq.status} and cannot be sent")
        if rfq.status == "DRAFT":
            rfq.status = "SENT"
            await self.db.flush()
        return rfq

    async def get_rfq(self, tenant_id: str, rfq_id: str) -> Optional[RFQ]:
        stmt = select(RFQ).options(selectinload(RFQ.items)).where(
            and_(RFQ.tenant_id == tenant_id, RFQ.id == rfq_id)
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    # -------------------------------------------------------------------------
    # 4. PURCHASE ORDERS (PO)
    # -------------------------------------------------------------------------
    async def create_purchase_order(
        self,
        tenant_id: str,
        supplier_id: str,
        warehouse_id: str,
        items_data: List[Dict[str, Any]],
        rfq_id: Optional[str] = None,
        currency: str = "MAD",
        payment_terms: str = "NET_30",
        notes: Optional[str] = None,
        expected_delivery_date: Optional[datetime] = None,
        user_id: Optional[str] = None,
        created_by_user_id: Optional[str] = None
    ) -> PurchaseOrder:
        user_creator = created_by_user_id or user_id
        count_stmt = select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id)
        res = await self.db.execute(count_stmt)
        seq = (res.scalar() or 0) + 1
        year = utc_now().year
        po_number = f"PO-{year}-{seq:05d}"

        subtotal_cents = 0
        for it in items_data:
            line_subtotal = it["quantity_ordered"] * it["unit_cost_cents"]
            subtotal_cents += line_subtotal

        tax_cents = int(subtotal_cents * 0.20)  # Standard 20% VAT
        grand_total_cents = subtotal_cents + tax_cents

        po = PurchaseOrder(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            po_number=po_number,
            supplier_id=supplier_id,
            warehouse_id=warehouse_id,
            rfq_id=rfq_id,
            status="DRAFT",
            version=1,
            currency=currency.upper(),
            subtotal_cents=subtotal_cents,
            tax_cents=tax_cents,
            grand_total_cents=grand_total_cents,
            payment_terms=payment_terms,
            notes=notes,
            expected_delivery_date=expected_delivery_date,
            created_by_user_id=user_creator
        )
        self.db.add(po)
        await self.db.flush()

        for it in items_data:
            line_subtotal = it["quantity_ordered"] * it["unit_cost_cents"]
            item = PurchaseOrderItem(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                purchase_order_id=po.id,
                product_id=it.get("product_id"),
                sku=it["sku"].upper().strip(),
                name=it["name"],
                quantity_ordered=it["quantity_ordered"],
                quantity_received=0,
                unit_cost_cents=it["unit_cost_cents"],
                subtotal_cents=line_subtotal
            )
            self.db.add(item)

        await self.db.flush()
        return await self.get_purchase_order(tenant_id, po.id)

    async def list_purchase_orders(self, tenant_id: str, status: Optional[str] = None, supplier_id: Optional[str] = None,
                                   warehouse_id: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[PurchaseOrder]:
        stmt = select(PurchaseOrder).options(selectinload(PurchaseOrder.items)).where(PurchaseOrder.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(PurchaseOrder.status == status)
        if supplier_id:
            stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
        if warehouse_id:
            stmt = stmt.where(PurchaseOrder.warehouse_id == warehouse_id)
        stmt = stmt.order_by(PurchaseOrder.created_at.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_goods_receipts(self, tenant_id: str, purchase_order_id: Optional[str] = None,
                                  warehouse_id: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[GoodsReceipt]:
        stmt = select(GoodsReceipt).options(selectinload(GoodsReceipt.items)).where(GoodsReceipt.tenant_id == tenant_id)
        if purchase_order_id:
            stmt = stmt.where(GoodsReceipt.purchase_order_id == purchase_order_id)
        if warehouse_id:
            stmt = stmt.where(GoodsReceipt.warehouse_id == warehouse_id)
        stmt = stmt.order_by(GoodsReceipt.created_at.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_goods_receipt(self, tenant_id: str, receipt_id: str) -> GoodsReceipt:
        stmt = select(GoodsReceipt).options(selectinload(GoodsReceipt.items)).where(
            and_(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.id == receipt_id))
        receipt = (await self.db.execute(stmt)).scalars().first()
        if not receipt:
            raise ProcurementError(f"Goods receipt {receipt_id} not found")
        return receipt

    async def list_stock_transfers(self, tenant_id: str, status: Optional[str] = None,
                                   limit: int = 50, offset: int = 0) -> List[StockTransfer]:
        stmt = select(StockTransfer).options(selectinload(StockTransfer.items)).where(StockTransfer.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(StockTransfer.status == status)
        stmt = stmt.order_by(StockTransfer.created_at.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_purchase_order(self, tenant_id: str, po_id: str) -> Optional[PurchaseOrder]:
        stmt = select(PurchaseOrder).options(selectinload(PurchaseOrder.items)).where(
            and_(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == po_id)
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def approve_purchase_order(
        self,
        tenant_id: str,
        po_id: str,
        user_id: Optional[str] = None,
        approved_by_user_id: Optional[str] = None
    ) -> PurchaseOrder:
        po = await self.get_purchase_order(tenant_id, po_id)
        if not po:
            raise PurchaseOrderNotFoundError(f"Purchase order '{po_id}' not found")
        if po.status != "DRAFT":
            raise InvalidPOStateTransitionError(f"Cannot approve PO in status '{po.status}'")

        po.status = "APPROVED"
        po.approved_by_user_id = approved_by_user_id or user_id
        po.approved_at = utc_now()
        po.version += 1
        await self.db.flush()
        return po

    async def issue_purchase_order(self, tenant_id: str, po_id: str) -> PurchaseOrder:
        po = await self.get_purchase_order(tenant_id, po_id)
        if not po:
            raise PurchaseOrderNotFoundError(f"Purchase order '{po_id}' not found")
        if po.status != "APPROVED":
            raise InvalidPOStateTransitionError(f"Cannot issue PO from status '{po.status}'")

        po.status = "ISSUED"
        po.issued_at = utc_now()
        po.version += 1
        await self.db.flush()
        return po

    # -------------------------------------------------------------------------
    # 5. GOODS RECEIPTS (GRN) & OVER-RECEIPT REJECTION
    # -------------------------------------------------------------------------
    async def record_goods_receipt(
        self,
        tenant_id: str,
        purchase_order_id: str,
        warehouse_id: str,
        items_data: List[Dict[str, Any]],
        carrier_name: Optional[str] = None,
        tracking_reference: Optional[str] = None,
        notes: Optional[str] = None,
        user_id: Optional[str] = None,
        received_by_user_id: Optional[str] = None
    ) -> GoodsReceipt:
        receiver_id = received_by_user_id or user_id
        """
        Records inbound delivery against an issued Purchase Order.
        Guarantees strict Over-Receipt Rejection:
        quantity_received + already_received cannot exceed quantity_ordered.
        Automatically increments inventory and appends to stock_movements ledger.
        """
        # Serialize receipts for the PO to prevent race conditions
        if purchase_order_id not in _po_receipt_locks:
            _po_receipt_locks[purchase_order_id] = asyncio.Lock()

        async with _po_receipt_locks[purchase_order_id]:
            # Acquire database-level transaction lock on PostgreSQL to guarantee multi-worker safety
            try:
                lock_id = abs(hash(f"po_receipt:{tenant_id}:{purchase_order_id}")) % (2**31)
                await self.db.execute(select(func.pg_advisory_xact_lock(lock_id)))
            except Exception:
                pass  # Supported across PostgreSQL; SQLite skips gracefully

            # Load PO with row-level lock
            stmt = select(PurchaseOrder).options(selectinload(PurchaseOrder.items)).where(
                and_(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == purchase_order_id)
            ).with_for_update()
            res = await self.db.execute(stmt)
            po = res.scalars().first()
            if not po:
                raise PurchaseOrderNotFoundError(f"Purchase order '{purchase_order_id}' not found")

            if po.status in ["RECEIVED", "CANCELLED", "CLOSED"]:
                raise OverReceiptError(
                    f"Over-receipt rejected on Purchase Order '{po.po_number}': PO is already in '{po.status}' status."
                )

            if po.status not in ["ISSUED", "PARTIALLY_RECEIVED"]:
                raise InvalidPOStateTransitionError(f"Cannot receive goods for PO in '{po.status}' status")

            po_items_map = {it.id: it for it in po.items}
            po_items_by_sku = {it.sku: it for it in po.items}

            # 1. Validate over-receipt across all receipt lines
            for rec_line in items_data:
                po_item = po_items_map.get(rec_line.get("po_item_id"))
                if not po_item:
                    po_item = po_items_by_sku.get(rec_line.get("sku", "").upper().strip())
                if not po_item:
                    raise ProcurementError(f"Item with SKU/ID '{rec_line.get('sku')}' not found on PO '{po.po_number}'")

                qty_received = rec_line["quantity_received"]
                remaining = po_item.quantity_ordered - po_item.quantity_received
                if qty_received > remaining:
                    raise OverReceiptError(
                        f"Over-receipt rejected on SKU '{po_item.sku}': Attempted to receive {qty_received} units, but only {remaining} remaining on PO (ordered: {po_item.quantity_ordered}, already received: {po_item.quantity_received})."
                    )

            # 2. Create Goods Receipt Header
            count_stmt = select(func.count()).select_from(GoodsReceipt).where(GoodsReceipt.tenant_id == tenant_id)
            c_res = await self.db.execute(count_stmt)
            seq = (c_res.scalar() or 0) + 1
            receipt_number = f"GRN-{utc_now().year}-{seq:05d}"

            grn = GoodsReceipt(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                receipt_number=receipt_number,
                purchase_order_id=po.id,
                warehouse_id=warehouse_id,
                received_by_user_id=receiver_id,
                carrier_name=carrier_name,
                tracking_reference=tracking_reference,
                notes=notes,
                received_at=utc_now()
            )
            self.db.add(grn)
            await self.db.flush()

            # 3. Process each line item & increment inventory ledger
            for rec_line in items_data:
                po_item = po_items_map.get(rec_line.get("po_item_id")) or po_items_by_sku.get(rec_line.get("sku", "").upper().strip())
                qty_received = rec_line["quantity_received"]
                qty_rejected = rec_line.get("quantity_rejected", 0)

                gr_item = GoodsReceiptItem(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    goods_receipt_id=grn.id,
                    po_item_id=po_item.id,
                    sku=po_item.sku,
                    quantity_received=qty_received,
                    quantity_rejected=qty_rejected,
                    rejection_reason=rec_line.get("rejection_reason"),
                    lot_number=rec_line.get("lot_number")
                )
                self.db.add(gr_item)

                # Update PO line quantity_received
                po_item.quantity_received += qty_received

                # Add to inventory if accepted units > 0
                accepted_qty = qty_received
                if accepted_qty > 0:
                    inv_item = await self.inventory_service.get_or_create_inventory_item(
                        tenant_id=tenant_id,
                        warehouse_id=warehouse_id,
                        sku=po_item.sku,
                        product_id=po_item.product_id
                    )
                    await self.inventory_service.adjust_stock(
                        tenant_id=tenant_id,
                        inventory_item_id=inv_item.id,
                        quantity_delta=accepted_qty,
                        movement_type="INBOUND_RECEIPT",
                        reference_type="GOODS_RECEIPT",
                        reference_id=grn.receipt_number,
                        user_id=receiver_id,
                        notes=f"Inbound receipt from PO {po.po_number}"
                    )

            # 4. Check if PO is completely received
            all_received = all(it.quantity_received >= it.quantity_ordered for it in po.items)
            po.status = "RECEIVED" if all_received else "PARTIALLY_RECEIVED"
            po.version += 1

            # 5. Emit audit event
            audit = AuditEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                actor_id=user_id,
                event_type="GOODS_RECEIPT_RECORDED",
                resource_type="goods_receipt",
                resource_id=grn.id,
                action="RECEIVE",
                status="SUCCESS",
                payload_json={
                    "grn_number": grn.receipt_number,
                    "po_number": po.po_number,
                    "all_received": all_received
                }
            )
            self.db.add(audit)
            await self.db.commit()

            # Reload with items
            stmt = select(GoodsReceipt).options(selectinload(GoodsReceipt.items)).where(
                and_(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.id == grn.id)
            )
            res = await self.db.execute(stmt)
            return res.scalars().first()

    # -------------------------------------------------------------------------
    # 6. INTER-WAREHOUSE STOCK TRANSFERS
    # -------------------------------------------------------------------------
    async def create_stock_transfer(
        self,
        tenant_id: str,
        source_warehouse_id: str,
        destination_warehouse_id: str,
        items_data: List[Dict[str, Any]],
        notes: Optional[str] = None,
        user_id: Optional[str] = None,
        created_by_user_id: Optional[str] = None
    ) -> StockTransfer:
        creator_id = created_by_user_id or user_id
        if source_warehouse_id == destination_warehouse_id:
            raise ProcurementError("Source and destination warehouses must be different.")

        count_stmt = select(func.count()).select_from(StockTransfer).where(StockTransfer.tenant_id == tenant_id)
        res = await self.db.execute(count_stmt)
        seq = (res.scalar() or 0) + 1
        transfer_number = f"TRF-{utc_now().year}-{seq:05d}"

        transfer = StockTransfer(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            transfer_number=transfer_number,
            source_warehouse_id=source_warehouse_id,
            destination_warehouse_id=destination_warehouse_id,
            status="REQUESTED",
            notes=notes,
            created_by_user_id=creator_id
        )
        self.db.add(transfer)
        await self.db.flush()

        for it in items_data:
            item = StockTransferItem(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                transfer_id=transfer.id,
                sku=it["sku"].upper().strip(),
                quantity_requested=it["quantity_requested"],
                quantity_shipped=0,
                quantity_received=0
            )
            self.db.add(item)

        await self.db.flush()
        return await self.get_stock_transfer(tenant_id, transfer.id)

    async def get_stock_transfer(self, tenant_id: str, transfer_id: str) -> Optional[StockTransfer]:
        stmt = select(StockTransfer).options(selectinload(StockTransfer.items)).where(
            and_(StockTransfer.tenant_id == tenant_id, StockTransfer.id == transfer_id)
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def approve_stock_transfer(self, tenant_id: str, transfer_id: str, user_id: Optional[str] = None) -> StockTransfer:
        transfer = await self.get_stock_transfer(tenant_id, transfer_id)
        if not transfer:
            raise StockTransferNotFoundError(f"Stock transfer '{transfer_id}' not found")
        if transfer.status not in ["REQUESTED", "DRAFT"]:
            raise ProcurementError(f"Cannot approve transfer in status '{transfer.status}'")
        transfer.status = "APPROVED"
        await self.db.flush()
        return transfer

    async def ship_stock_transfer(self, tenant_id: str, transfer_id: str, user_id: Optional[str] = None) -> StockTransfer:
        """Dispatches stock from origin warehouse, placing it IN_TRANSIT."""
        transfer = await self.get_stock_transfer(tenant_id, transfer_id)
        if not transfer:
            raise StockTransferNotFoundError(f"Stock transfer '{transfer_id}' not found")
        if transfer.status not in ["REQUESTED", "APPROVED"]:
            raise ProcurementError(f"Cannot ship transfer in status '{transfer.status}'")

        lock_key = f"{tenant_id}:{transfer.source_warehouse_id}"
        async with get_transfer_ship_lock(lock_key):
            # Acquire database-level transaction lock on PostgreSQL to guarantee multi-worker safety
            try:
                lock_id = abs(hash(f"stock_transfer:{tenant_id}:{transfer.source_warehouse_id}")) % (2**31)
                await self.db.execute(select(func.pg_advisory_xact_lock(lock_id)))
            except Exception:
                pass  # Supported across PostgreSQL; SQLite skips gracefully

            # Verify stock and deduct from source warehouse
            for it in transfer.items:
                source_item = await self.inventory_service.get_or_create_inventory_item(
                    tenant_id=tenant_id,
                    warehouse_id=transfer.source_warehouse_id,
                    sku=it.sku
                )
                if source_item.available_to_promise < it.quantity_requested:
                    raise InsufficientTransferStockError(
                        f"Insufficient on-hand stock at source warehouse for SKU '{it.sku}'."
                    )

                # Deduct from source
                await self.inventory_service.adjust_stock(
                    tenant_id=tenant_id,
                    inventory_item_id=source_item.id,
                    quantity_delta=-it.quantity_requested,
                    movement_type="TRANSFER",
                    reference_type="STOCK_TRANSFER",
                    reference_id=transfer.transfer_number,
                    user_id=user_id,
                    notes=f"Shipped transfer to warehouse {transfer.destination_warehouse_id}"
                )
                it.quantity_shipped = it.quantity_requested

            transfer.status = "IN_TRANSIT"
            transfer.shipped_at = utc_now()
            await self.db.commit()
            return transfer

    async def receive_stock_transfer(self, tenant_id: str, transfer_id: str, user_id: Optional[str] = None) -> StockTransfer:
        """Receives in-transit stock at destination warehouse."""
        transfer = await self.get_stock_transfer(tenant_id, transfer_id)
        if not transfer:
            raise StockTransferNotFoundError(f"Stock transfer '{transfer_id}' not found")
        if transfer.status != "IN_TRANSIT":
            raise ProcurementError(f"Cannot receive transfer in status '{transfer.status}'")

        # Add to destination warehouse
        for it in transfer.items:
            dest_item = await self.inventory_service.get_or_create_inventory_item(
                tenant_id=tenant_id,
                warehouse_id=transfer.destination_warehouse_id,
                sku=it.sku
            )
            await self.inventory_service.adjust_stock(
                tenant_id=tenant_id,
                inventory_item_id=dest_item.id,
                quantity_delta=it.quantity_shipped,
                movement_type="TRANSFER",
                reference_type="STOCK_TRANSFER",
                reference_id=transfer.transfer_number,
                user_id=user_id,
                notes=f"Received transfer from warehouse {transfer.source_warehouse_id}"
            )
            it.quantity_received = it.quantity_shipped

        transfer.status = "RECEIVED"
        transfer.received_at = utc_now()
        await self.db.flush()
        return transfer
