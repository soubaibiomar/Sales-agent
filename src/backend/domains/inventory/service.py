"""
Inventory Domain Service.
Manages Warehouses, Inventory Items, Available-To-Promise (ATP),
Atomic Stock Holds, Reservation Expiry, and the Append-Only Stock Movements Ledger.
Step 05: Sprint 3 - Transact
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

_sku_locks: Dict[str, asyncio.Lock] = {}

def get_sku_lock(key: str) -> asyncio.Lock:
    if key not in _sku_locks:
        _sku_locks[key] = asyncio.Lock()
    return _sku_locks[key]

from src.backend.models.entities import (
    Warehouse, InventoryItem, StockReservation, StockMovement, AuditEvent
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InventoryError(Exception):
    pass


class InsufficientStockError(InventoryError):
    pass


class ReservationNotFoundError(InventoryError):
    pass


class ReservationAlreadyResolvedError(InventoryError):
    pass


class InventoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_warehouse(
        self,
        tenant_id: str,
        code: str,
        name: str,
        address_json: str = "{}"
    ) -> Warehouse:
        warehouse = Warehouse(
            tenant_id=tenant_id,
            code=code.upper(),
            name=name,
            address_json=address_json,
            is_active=True
        )
        self.db.add(warehouse)
        await self.db.flush()
        return warehouse

    async def get_warehouse_by_code(self, tenant_id: str, code: str) -> Optional[Warehouse]:
        stmt = select(Warehouse).where(
            and_(Warehouse.tenant_id == tenant_id, Warehouse.code == code.upper())
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_warehouses(self, tenant_id: str) -> List[Warehouse]:
        stmt = select(Warehouse).where(Warehouse.tenant_id == tenant_id).order_by(Warehouse.code.asc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_or_create_inventory_item(
        self,
        tenant_id: str,
        warehouse_id: str,
        sku: str,
        product_id: Optional[str] = None,
        variant_id: Optional[str] = None,
        initial_on_hand: int = 0,
        backorder_allowed: bool = False
    ) -> InventoryItem:
        sku = sku.upper()
        stmt = select(InventoryItem).where(
            and_(
                InventoryItem.tenant_id == tenant_id,
                InventoryItem.warehouse_id == warehouse_id,
                InventoryItem.sku == sku
            )
        )
        res = await self.db.execute(stmt)
        item = res.scalar_one_or_none()
        if item:
            return item

        item = InventoryItem(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            product_id=product_id,
            variant_id=variant_id,
            sku=sku,
            on_hand_quantity=initial_on_hand,
            reserved_quantity=0,
            allocated_quantity=0,
            backorder_allowed=backorder_allowed
        )
        self.db.add(item)
        await self.db.flush()

        if initial_on_hand > 0:
            movement = StockMovement(
                tenant_id=tenant_id,
                inventory_item_id=item.id,
                movement_type="INBOUND_RECEIPT",
                quantity_delta=initial_on_hand,
                previous_on_hand=0,
                new_on_hand=initial_on_hand,
                reference_type="INITIAL_SETUP",
                reference_id="INIT",
                notes="Initial inventory setup"
            )
            self.db.add(movement)
            await self.db.flush()

        return item

    async def adjust_stock(
        self,
        tenant_id: str,
        inventory_item_id: str,
        quantity_delta: int,
        movement_type: str = "ADJUSTMENT",
        reference_type: str = "MANUAL_ADJUSTMENT",
        reference_id: str = "MANUAL",
        notes: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> InventoryItem:
        stmt = select(InventoryItem).where(
            and_(InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id)
        ).with_for_update()
        res = await self.db.execute(stmt)
        item = res.scalar_one_or_none()
        if not item:
            raise InventoryError("Inventory item not found")

        prev_on_hand = item.on_hand_quantity
        new_on_hand = prev_on_hand + quantity_delta
        if new_on_hand < 0:
            raise InventoryError(f"Cannot adjust stock below 0: current={prev_on_hand}, delta={quantity_delta}")

        item.on_hand_quantity = new_on_hand

        movement = StockMovement(
            tenant_id=tenant_id,
            inventory_item_id=item.id,
            movement_type=movement_type,
            quantity_delta=quantity_delta,
            previous_on_hand=prev_on_hand,
            new_on_hand=new_on_hand,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            created_by_user_id=user_id
        )
        self.db.add(movement)
        await self.db.flush()
        return item

    async def reserve_stock(
        self,
        tenant_id: str,
        sku: str,
        quantity: int,
        warehouse_id: Optional[str] = None,
        order_id: Optional[str] = None,
        quote_id: Optional[str] = None,
        duration_seconds: int = 1800,
        idempotency_key: Optional[str] = None
    ) -> StockReservation:
        sku = sku.upper()
        if quantity <= 0:
            raise InventoryError("Reservation quantity must be greater than zero")

        async with get_sku_lock(f"{tenant_id}_{sku}"):
            # Idempotency check
            if idempotency_key:
                stmt = select(StockReservation).where(
                    and_(
                        StockReservation.tenant_id == tenant_id,
                        StockReservation.idempotency_key == idempotency_key
                    )
                )
                res = await self.db.execute(stmt)
                existing = res.scalar_one_or_none()
                if existing:
                    return existing

            # Locate warehouse item with pessimistic lock
            query = select(InventoryItem).where(
                and_(InventoryItem.tenant_id == tenant_id, InventoryItem.sku == sku)
            )
            if warehouse_id:
                query = query.where(InventoryItem.warehouse_id == warehouse_id)

            query = query.with_for_update()
            res = await self.db.execute(query)
            item = res.scalar_one_or_none()

            if not item:
                raise InventoryError(f"No inventory record found for SKU {sku}")

            # Compute Available-to-Promise: on_hand - reserved - allocated
            atp = item.on_hand_quantity - item.reserved_quantity - item.allocated_quantity
            if atp < quantity and not item.backorder_allowed:
                raise InsufficientStockError(
                    f"Insufficient stock for SKU {sku}: requested={quantity}, available_to_promise={max(0, atp)}"
                )

            # Atomic reservation hold
            item.reserved_quantity += quantity
            reserved_until = utc_now() + timedelta(seconds=duration_seconds)

            reservation = StockReservation(
                tenant_id=tenant_id,
                inventory_item_id=item.id,
                order_id=order_id,
                quote_id=quote_id,
                sku=sku,
                quantity=quantity,
                status="ACTIVE",
                reserved_until=reserved_until,
                idempotency_key=idempotency_key
            )
            self.db.add(reservation)
            await self.db.flush()
            return reservation

    async def commit_reservation(
        self,
        tenant_id: str,
        reservation_id: str,
        reference_id: str,
        user_id: Optional[str] = None
    ) -> StockReservation:
        stmt = select(StockReservation).where(
            and_(StockReservation.id == reservation_id, StockReservation.tenant_id == tenant_id)
        ).with_for_update()
        res = await self.db.execute(stmt)
        reservation = res.scalar_one_or_none()
        if not reservation:
            raise ReservationNotFoundError("Reservation not found")

        if reservation.status != "ACTIVE":
            if reservation.status == "COMMITTED":
                return reservation  # Idempotent
            raise ReservationAlreadyResolvedError(f"Cannot commit reservation with status {reservation.status}")

        # Lock inventory item
        item_stmt = select(InventoryItem).where(
            InventoryItem.id == reservation.inventory_item_id
        ).with_for_update()
        item_res = await self.db.execute(item_stmt)
        item = item_res.scalar_one()

        # Commit deduction: on_hand and reserved decrease by reservation quantity
        prev_on_hand = item.on_hand_quantity
        new_on_hand = prev_on_hand - reservation.quantity
        item.on_hand_quantity = max(0, new_on_hand)
        item.reserved_quantity = max(0, item.reserved_quantity - reservation.quantity)
        reservation.status = "COMMITTED"

        movement = StockMovement(
            tenant_id=tenant_id,
            inventory_item_id=item.id,
            movement_type="SALE_DEDUCTION",
            quantity_delta=-reservation.quantity,
            previous_on_hand=prev_on_hand,
            new_on_hand=new_on_hand,
            reference_type="ORDER_COMMITTED",
            reference_id=reference_id,
            notes=f"Stock committed for reservation {reservation.id}",
            created_by_user_id=user_id
        )
        self.db.add(movement)
        await self.db.flush()
        return reservation

    async def release_reservation(
        self,
        tenant_id: str,
        reservation_id: str,
        reason: str = "CANCELLED"
    ) -> StockReservation:
        stmt = select(StockReservation).where(
            and_(StockReservation.id == reservation_id, StockReservation.tenant_id == tenant_id)
        ).with_for_update()
        res = await self.db.execute(stmt)
        reservation = res.scalar_one_or_none()
        if not reservation:
            raise ReservationNotFoundError("Reservation not found")

        if reservation.status != "ACTIVE":
            if reservation.status in ("RELEASED", "EXPIRED"):
                return reservation
            raise ReservationAlreadyResolvedError(f"Cannot release reservation with status {reservation.status}")

        item_stmt = select(InventoryItem).where(
            InventoryItem.id == reservation.inventory_item_id
        ).with_for_update()
        item_res = await self.db.execute(item_stmt)
        item = item_res.scalar_one()

        item.reserved_quantity = max(0, item.reserved_quantity - reservation.quantity)
        reservation.status = "RELEASED" if reason != "EXPIRED" else "EXPIRED"
        await self.db.flush()
        return reservation

    async def expire_stale_reservations(self, tenant_id: Optional[str] = None) -> int:
        now = utc_now()
        stmt = select(StockReservation).where(
            and_(
                StockReservation.status == "ACTIVE",
                StockReservation.reserved_until < now
            )
        )
        if tenant_id:
            stmt = stmt.where(StockReservation.tenant_id == tenant_id)

        stmt = stmt.with_for_update()
        res = await self.db.execute(stmt)
        expired_reservations = list(res.scalars().all())

        expired_count = 0
        for reservation in expired_reservations:
            item_stmt = select(InventoryItem).where(
                InventoryItem.id == reservation.inventory_item_id
            ).with_for_update()
            item_res = await self.db.execute(item_stmt)
            item = item_res.scalar_one_or_none()
            if item:
                item.reserved_quantity = max(0, item.reserved_quantity - reservation.quantity)
            reservation.status = "EXPIRED"
            expired_count += 1

        if expired_count > 0:
            await self.db.flush()

        return expired_count

    async def get_inventory_items(
        self,
        tenant_id: str,
        warehouse_id: Optional[str] = None,
        sku: Optional[str] = None
    ) -> List[InventoryItem]:
        query = select(InventoryItem).where(InventoryItem.tenant_id == tenant_id)
        if warehouse_id:
            query = query.where(InventoryItem.warehouse_id == warehouse_id)
        if sku:
            query = query.where(InventoryItem.sku == sku.upper())
        query = query.order_by(InventoryItem.sku.asc())
        res = await self.db.execute(query)
        return list(res.scalars().all())

    async def get_stock_movements(
        self,
        tenant_id: str,
        inventory_item_id: Optional[str] = None
    ) -> List[StockMovement]:
        query = select(StockMovement).where(StockMovement.tenant_id == tenant_id)
        if inventory_item_id:
            query = query.where(StockMovement.inventory_item_id == inventory_item_id)
        query = query.order_by(StockMovement.created_at.desc())
        res = await self.db.execute(query)
        return list(res.scalars().all())
