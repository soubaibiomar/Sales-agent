"""
Logistics & Fulfillment Domain Service.
Pick, Pack, Ship, Carrier Integrations, Tracking Normalization, Monotonic Status Protection,
and Proof of Delivery.
(Controls 16, 21, 22, 57, 58)
Step 06: Sprint 3 - Operate
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.models.entities import (
    Shipment, ShipmentItem, ShipmentTrackingEvent, DeliveryProof,
    SalesOrder, OrderItem, Warehouse, StockMovement, InventoryItem, AuditEvent
)
from src.backend.integrations.carriers.base import (
    CarrierAdapter, CarrierRateQuote, CarrierTrackingEvent
)
from src.backend.integrations.carriers.amana import AmanaCarrierAdapter
from src.backend.integrations.carriers.simulator import SimulatedExpressCarrierAdapter


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LogisticsError(Exception):
    pass


class ShipmentNotFoundError(LogisticsError):
    pass


class InvalidShipmentStateError(LogisticsError):
    pass


class InsufficientStockForShipmentError(LogisticsError):
    """Raised when a shipment would ship more units than the warehouse ledger holds."""


class CarrierNotFoundError(LogisticsError):
    pass


# Strict monotonic rank mapping for shipment progression
# Higher rank wins; lower rank cannot overwrite higher rank
SHIPMENT_STATUS_RANKS = {
    "CREATED": 1,
    "PICKING": 2,
    "PACKED": 3,
    "SHIPPED": 4,
    "IN_TRANSIT": 5,
    "OUT_FOR_DELIVERY": 6,
    "DELIVERED": 7,
    "FAILED": 7,      # Terminal
    "RETURNED": 7,    # Terminal
    "CANCELLED": 7,   # Terminal
}

TERMINAL_STATUSES = {"DELIVERED", "FAILED", "RETURNED", "CANCELLED"}


class LogisticsService:
    def __init__(self, db: AsyncSession, carriers: Optional[Dict[str, CarrierAdapter]] = None):
        self.db = db
        self.carriers = carriers or {
            "AMANA": AmanaCarrierAdapter(),
            "SIMULATED_EXPRESS": SimulatedExpressCarrierAdapter(),
        }

    def register_carrier(self, carrier: CarrierAdapter) -> None:
        self.carriers[carrier.carrier_code.upper()] = carrier

    def get_carrier(self, carrier_code: str) -> CarrierAdapter:
        adapter = self.carriers.get(carrier_code.upper())
        if not adapter:
            raise CarrierNotFoundError(f"Carrier adapter '{carrier_code}' is not registered.")
        return adapter

    # -------------------------------------------------------------------------
    # 1. RATE QUOTING
    # -------------------------------------------------------------------------
    async def get_multi_carrier_quotes(
        self,
        origin_address: Dict[str, Any],
        destination_address: Dict[str, Any],
        weight_grams: int = 1000,
        dimensions_cm: Optional[Dict[str, float]] = None
    ) -> List[CarrierRateQuote]:
        quotes: List[CarrierRateQuote] = []
        for code, adapter in self.carriers.items():
            try:
                adapter_quotes = await adapter.get_rate_quotes(
                    origin_address=origin_address,
                    destination_address=destination_address,
                    weight_grams=weight_grams,
                    dimensions_cm=dimensions_cm
                )
                quotes.extend(adapter_quotes)
            except Exception:
                # Tolerate single provider failure during multi-carrier quoting
                continue
        quotes.sort(key=lambda q: q.cost_cents)
        return quotes

    # -------------------------------------------------------------------------
    # 2. SHIPMENT CREATION
    # -------------------------------------------------------------------------
    async def create_shipment(
        self,
        tenant_id: str,
        order_id: str,
        warehouse_id: str,
        carrier_code: str,
        shipping_address: Dict[str, Any],
        delivery_contact: Dict[str, Any],
        items_data: List[Dict[str, Any]],
        carrier_service: Optional[str] = None,
        created_by_user_id: Optional[str] = None
    ) -> Shipment:
        """Creates a shipment record from a confirmed sales order."""
        # 1. Validate SalesOrder
        stmt_order = select(SalesOrder).where(
            and_(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
        ).options(selectinload(SalesOrder.items))
        res_order = await self.db.execute(stmt_order)
        order = res_order.scalar_one_or_none()
        if not order:
            raise LogisticsError(f"Sales order '{order_id}' not found.")

        # 2. Validate warehouse
        stmt_wh = select(Warehouse).where(
            and_(Warehouse.tenant_id == tenant_id, Warehouse.id == warehouse_id)
        )
        res_wh = await self.db.execute(stmt_wh)
        wh = res_wh.scalar_one_or_none()
        if not wh:
            raise LogisticsError(f"Warehouse '{warehouse_id}' not found.")

        # 3. Generate shipment number
        count_stmt = select(func.count()).select_from(Shipment).where(Shipment.tenant_id == tenant_id)
        res_count = await self.db.execute(count_stmt)
        seq = (res_count.scalar() or 0) + 1
        shipment_number = f"SHP-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{seq:04d}"

        carrier_code_upper = carrier_code.upper().strip()
        shipment = Shipment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            shipment_number=shipment_number,
            order_id=order_id,
            warehouse_id=warehouse_id,
            carrier_code=carrier_code_upper,
            carrier_service=carrier_service,
            status="CREATED",
            shipping_address_json=shipping_address,
            delivery_contact_json=delivery_contact,
            created_by_user_id=created_by_user_id
        )
        self.db.add(shipment)
        await self.db.flush()

        # 4. Attach shipment items
        for item_in in items_data:
            s_item = ShipmentItem(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                shipment_id=shipment.id,
                order_item_id=item_in["order_item_id"],
                sku=item_in["sku"],
                name=item_in.get("name", item_in["sku"]),
                quantity=item_in["quantity"]
            )
            self.db.add(s_item)

        # 5. Record initial tracking event
        initial_event = ShipmentTrackingEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            shipment_id=shipment.id,
            status="CREATED",
            event_timestamp=utc_now(),
            location=wh.name,
            description="Shipment created in fulfillment queue",
            raw_payload_json={"status": "CREATED"}
        )
        self.db.add(initial_event)
        await self.db.flush()

        return await self.get_shipment(tenant_id, shipment.id)

    # -------------------------------------------------------------------------
    # 3. FULFILLMENT LIFECYCLE: PICK, PACK, SHIP
    # -------------------------------------------------------------------------
    async def start_picking(self, tenant_id: str, shipment_id: str) -> Shipment:
        shipment = await self.get_shipment(tenant_id, shipment_id)
        if shipment.status != "CREATED":
            raise InvalidShipmentStateError(f"Cannot start picking from status '{shipment.status}'.")

        shipment.status = "PICKING"
        self._record_tracking_event(shipment, "PICKING", "Warehouse Floor", "Picking items for package assembly")
        await self.db.flush()
        return await self.get_shipment(tenant_id, shipment.id)

    async def complete_packing(self, tenant_id: str, shipment_id: str) -> Shipment:
        shipment = await self.get_shipment(tenant_id, shipment_id)
        if shipment.status != "PICKING":
            raise InvalidShipmentStateError(f"Cannot pack from status '{shipment.status}'.")

        shipment.status = "PACKED"
        self._record_tracking_event(shipment, "PACKED", "Packing Station", "Package sealed and labeled")
        await self.db.flush()
        return await self.get_shipment(tenant_id, shipment.id)

    async def book_carrier_and_ship(
        self,
        tenant_id: str,
        shipment_id: str,
        weight_grams: int = 1000
    ) -> Shipment:
        """Books carrier API, receives tracking number & label, transitions to SHIPPED, and deducts inventory."""
        shipment = await self.get_shipment(tenant_id, shipment_id)
        if shipment.status not in ("PACKED", "PICKING", "CREATED"):
            raise InvalidShipmentStateError(f"Cannot dispatch shipment from status '{shipment.status}'.")

        adapter = self.get_carrier(shipment.carrier_code)

        # Get items for carrier booking
        items_payload = [{"sku": i.sku, "quantity": i.quantity} for i in shipment.items]

        # Call carrier adapter
        booking_result = await adapter.book_shipment(
            shipment_number=shipment.shipment_number,
            origin_address=shipment.shipping_address_json,
            destination_address=shipment.shipping_address_json,
            delivery_contact=shipment.delivery_contact_json,
            items=items_payload,
            weight_grams=weight_grams
        )

        shipment.tracking_number = booking_result.tracking_number
        shipment.shipping_label_url = booking_result.shipping_label_url
        shipment.estimated_delivery_at = booking_result.estimated_delivery_at
        shipment.status = "SHIPPED"
        shipment.shipped_at = utc_now()

        # Record stock movement (deduct inventory)
        for item in shipment.items:
            # Find inventory item
            stmt_inv = select(InventoryItem).where(
                and_(
                    InventoryItem.tenant_id == tenant_id,
                    InventoryItem.warehouse_id == shipment.warehouse_id,
                    InventoryItem.sku == item.sku
                )
            )
            res_inv = await self.db.execute(stmt_inv)
            inv = res_inv.scalar_one_or_none()
            if not inv:
                inv = InventoryItem(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    warehouse_id=shipment.warehouse_id,
                    sku=item.sku,
                    on_hand_quantity=0,
                    reserved_quantity=0,
                    allocated_quantity=0
                )
                self.db.add(inv)
                await self.db.flush()

            prev_on = inv.on_hand_quantity
            # Warehouse balance is ledger-backed: never ship units that are not on hand
            # (previously the balance silently went negative; migration 012 now also
            # rejects negative balances at the database level).
            if inv.on_hand_quantity < item.quantity:
                raise InsufficientStockForShipmentError(
                    f"Cannot ship {item.quantity} x {item.sku} from warehouse {shipment.warehouse_id}: "
                    f"only {inv.on_hand_quantity} on hand."
                )
            inv.on_hand_quantity -= item.quantity
            inv.reserved_quantity = max(0, inv.reserved_quantity - item.quantity)
            new_on = inv.on_hand_quantity

            movement = StockMovement(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                inventory_item_id=inv.id,
                movement_type="SALE_DEDUCTION",
                quantity_delta=-item.quantity,
                previous_on_hand=prev_on,
                new_on_hand=new_on,
                reference_type="SHIPMENT",
                reference_id=shipment.id,
                notes=f"Shipment {shipment.shipment_number} dispatched via {shipment.carrier_code}"
            )
            self.db.add(movement)

        self._record_tracking_event(
            shipment,
            "SHIPPED",
            "Warehouse Outbound Bay",
            f"Handed over to carrier {shipment.carrier_code}. Tracking: {shipment.tracking_number}"
        )
        await self.db.flush()
        return await self.get_shipment(tenant_id, shipment.id)

    # -------------------------------------------------------------------------
    # 4. MONOTONIC TRACKING EVENTS & WEBHOOK HANDLER
    # -------------------------------------------------------------------------
    async def process_carrier_webhook(
        self,
        tenant_id: str,
        carrier_code: str,
        headers: Dict[str, str],
        raw_body: bytes,
        payload: Dict[str, Any],
        secret: str
    ) -> List[ShipmentTrackingEvent]:
        """Validates webhook signature, normalizes events, and applies monotonic updates."""
        adapter = self.get_carrier(carrier_code)
        if not adapter.verify_webhook_signature(headers, raw_body, secret):
            raise LogisticsError("Invalid carrier webhook HMAC signature.")

        events = adapter.parse_tracking_webhook(headers, payload)
        saved_events = []

        tracking_number = payload.get("tracking_number") or payload.get("tracking_id")
        if not tracking_number:
            raise LogisticsError("Carrier webhook payload missing tracking_number.")

        # Find shipment by tracking number
        stmt = select(Shipment).where(
            and_(
                Shipment.tenant_id == tenant_id,
                Shipment.tracking_number == str(tracking_number).strip()
            )
        ).options(selectinload(Shipment.items), selectinload(Shipment.tracking_events))
        res = await self.db.execute(stmt)
        shipment = res.scalar_one_or_none()
        if not shipment:
            raise ShipmentNotFoundError(f"Shipment with tracking number '{tracking_number}' not found.")

        for ev in events:
            # Check monotonic invariant
            self._apply_monotonic_status(shipment, ev.status)

            tracking_ev = ShipmentTrackingEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                shipment_id=shipment.id,
                status=ev.status,
                event_timestamp=ev.event_timestamp,
                location=ev.location,
                description=ev.description,
                raw_payload_json=ev.raw_payload
            )
            self.db.add(tracking_ev)
            saved_events.append(tracking_ev)

        await self.db.flush()
        return saved_events

    def _apply_monotonic_status(self, shipment: Shipment, new_status: str) -> bool:
        """Applies status change only if new_status rank >= current status rank and not terminal."""
        current_status = shipment.status
        if current_status in TERMINAL_STATUSES:
            # Absorbing state: late callbacks cannot regress or alter DELIVERED/FAILED/RETURNED
            return False

        current_rank = SHIPMENT_STATUS_RANKS.get(current_status, 0)
        new_rank = SHIPMENT_STATUS_RANKS.get(new_status, 0)

        if new_rank >= current_rank:
            shipment.status = new_status
            if new_status == "DELIVERED":
                shipment.delivered_at = utc_now()
            elif new_status == "FAILED":
                shipment.failed_at = utc_now()
            return True
        return False

    # -------------------------------------------------------------------------
    # 5. DELIVERY PROOF
    # -------------------------------------------------------------------------
    async def record_delivery_proof(
        self,
        tenant_id: str,
        shipment_id: str,
        recipient_name: str,
        signature_image_url: Optional[str] = None,
        photo_url: Optional[str] = None,
        location_coordinates: Optional[str] = None
    ) -> DeliveryProof:
        shipment = await self.get_shipment(tenant_id, shipment_id)

        # Check if proof already exists
        stmt_p = select(DeliveryProof).where(
            and_(DeliveryProof.tenant_id == tenant_id, DeliveryProof.shipment_id == shipment_id)
        )
        res_p = await self.db.execute(stmt_p)
        existing = res_p.scalar_one_or_none()
        if existing:
            return existing

        proof = DeliveryProof(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            shipment_id=shipment.id,
            recipient_name=recipient_name.strip(),
            signature_image_url=signature_image_url,
            photo_url=photo_url,
            location_coordinates=location_coordinates,
            signed_at=utc_now()
        )
        self.db.add(proof)

        # Transition status to DELIVERED monotonically
        self._apply_monotonic_status(shipment, "DELIVERED")
        self._record_tracking_event(
            shipment,
            "DELIVERED",
            location_coordinates or "Recipient Address",
            f"Delivered and signed by {recipient_name}"
        )
        await self.db.flush()
        return proof

    # -------------------------------------------------------------------------
    # 6. RETRIEVAL HELPERS
    # -------------------------------------------------------------------------
    async def get_shipment(self, tenant_id: str, shipment_id: str) -> Shipment:
        stmt = select(Shipment).where(
            and_(Shipment.tenant_id == tenant_id, Shipment.id == shipment_id)
        ).options(
            selectinload(Shipment.items),
            selectinload(Shipment.tracking_events),
            selectinload(Shipment.delivery_proof)
        )
        res = await self.db.execute(stmt)
        shipment = res.scalar_one_or_none()
        if not shipment:
            raise ShipmentNotFoundError(f"Shipment '{shipment_id}' not found.")
        return shipment

    async def list_shipments(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        order_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Shipment]:
        conditions = [Shipment.tenant_id == tenant_id]
        if status:
            conditions.append(Shipment.status == status.upper())
        if order_id:
            conditions.append(Shipment.order_id == order_id)

        stmt = select(Shipment).where(and_(*conditions)).order_by(
            Shipment.created_at.desc()
        ).limit(limit).offset(offset).options(
            selectinload(Shipment.items),
            selectinload(Shipment.delivery_proof)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    def _record_tracking_event(
        self,
        shipment: Shipment,
        status: str,
        location: str,
        description: str
    ) -> ShipmentTrackingEvent:
        ev = ShipmentTrackingEvent(
            id=str(uuid.uuid4()),
            tenant_id=shipment.tenant_id,
            shipment_id=shipment.id,
            status=status,
            event_timestamp=utc_now(),
            location=location,
            description=description,
            raw_payload_json={"status": status}
        )
        self.db.add(ev)
        return ev
