"""
Customer Support, Warranty & Return Merchandise Authorization (RMA) Domain Service.
Support tickets, warranty eligibility verification, RMA inspection workflows,
and refund handoffs.
(Controls 05, 06, 07, 16, 21, 22, 57, 58)
Step 06: Sprint 3 - Operate
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.models.entities import (
    SupportTicket, TicketMessage, WarrantyClaim, ReturnAuthorization, ReturnItem,
    SalesOrder, OrderItem, Warehouse, InventoryItem, StockMovement, AuditEvent
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SupportError(Exception):
    pass


class TicketNotFoundError(SupportError):
    pass


class WarrantyClaimNotFoundError(SupportError):
    pass


class RMANotFoundError(SupportError):
    pass


class InvalidReturnStateError(SupportError):
    pass


class WarrantyExpiredError(SupportError):
    pass


# Configurable default warranty duration (365 days business policy baseline)
# Note: Warranty windows are treated as configurable business policies per tenant/product,
# rather than unsupported universal legal requirements.
DEFAULT_WARRANTY_DAYS = 365


class SupportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # 1. SUPPORT TICKETS
    # -------------------------------------------------------------------------
    async def create_ticket(
        self,
        tenant_id: str,
        subject: str,
        description: str,
        category: str = "GENERAL",
        priority: str = "MEDIUM",
        order_id: Optional[str] = None,
        account_id: Optional[str] = None,
        contact_id: Optional[str] = None,
        assigned_user_id: Optional[str] = None
    ) -> SupportTicket:
        # Generate ticket sequence
        count_stmt = select(func.count()).select_from(SupportTicket).where(
            SupportTicket.tenant_id == tenant_id
        )
        res_count = await self.db.execute(count_stmt)
        seq = (res_count.scalar() or 0) + 1
        ticket_number = f"TCK-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{seq:04d}"

        ticket = SupportTicket(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            ticket_number=ticket_number,
            account_id=account_id,
            contact_id=contact_id,
            order_id=order_id,
            priority=priority.upper(),
            category=category.upper(),
            status="OPEN",
            subject=subject.strip(),
            description=description.strip(),
            assigned_user_id=assigned_user_id
        )
        self.db.add(ticket)
        await self.db.flush()

        # Add initial customer message to thread
        first_msg = TicketMessage(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            ticket_id=ticket.id,
            sender_type="CUSTOMER",
            message_text=description.strip()
        )
        self.db.add(first_msg)
        await self.db.flush()
        return await self.get_ticket(tenant_id, ticket.id)

    async def add_message(
        self,
        tenant_id: str,
        ticket_id: str,
        sender_type: str,
        message_text: str,
        sender_user_id: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> TicketMessage:
        ticket = await self.get_ticket(tenant_id, ticket_id)
        msg = TicketMessage(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            ticket_id=ticket.id,
            sender_type=sender_type.upper(),
            sender_user_id=sender_user_id,
            message_text=message_text.strip(),
            attachments_json=attachments or []
        )
        self.db.add(msg)

        # Update ticket status if customer replied
        if sender_type.upper() == "CUSTOMER" and ticket.status in ("RESOLVED", "PENDING_CUSTOMER"):
            ticket.status = "IN_PROGRESS"
        elif sender_type.upper() == "AGENT" and ticket.status == "OPEN":
            ticket.status = "IN_PROGRESS"

        await self.db.flush()
        return msg

    async def update_ticket_status(
        self,
        tenant_id: str,
        ticket_id: str,
        new_status: str,
        assigned_user_id: Optional[str] = None
    ) -> SupportTicket:
        ticket = await self.get_ticket(tenant_id, ticket_id)
        ticket.status = new_status.upper()
        if assigned_user_id:
            ticket.assigned_user_id = assigned_user_id
        if ticket.status == "RESOLVED":
            ticket.resolved_at = utc_now()
        elif ticket.status == "CLOSED":
            ticket.closed_at = utc_now()

        await self.db.flush()
        return await self.get_ticket(tenant_id, ticket.id)

    async def get_ticket(self, tenant_id: str, ticket_id: str) -> SupportTicket:
        stmt = select(SupportTicket).where(
            and_(SupportTicket.tenant_id == tenant_id, SupportTicket.id == ticket_id)
        ).options(
            selectinload(SupportTicket.messages),
            selectinload(SupportTicket.order),
            selectinload(SupportTicket.account),
            selectinload(SupportTicket.contact)
        )
        res = await self.db.execute(stmt)
        ticket = res.scalar_one_or_none()
        if not ticket:
            raise TicketNotFoundError(f"Support ticket '{ticket_id}' not found.")
        return ticket

    async def list_tickets(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        category: Optional[str] = None,
        order_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[SupportTicket]:
        conditions = [SupportTicket.tenant_id == tenant_id]
        if status:
            conditions.append(SupportTicket.status == status.upper())
        if category:
            conditions.append(SupportTicket.category == category.upper())
        if order_id:
            conditions.append(SupportTicket.order_id == order_id)

        stmt = select(SupportTicket).where(and_(*conditions)).order_by(
            SupportTicket.created_at.desc()
        ).limit(limit).offset(offset).options(
            selectinload(SupportTicket.messages)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    # -------------------------------------------------------------------------
    # 2. WARRANTY CLAIMS
    # -------------------------------------------------------------------------
    async def create_warranty_claim(
        self,
        tenant_id: str,
        order_id: str,
        order_item_id: str,
        sku: str,
        claim_reason: str,
        serial_number: Optional[str] = None,
        ticket_id: Optional[str] = None,
        warranty_days: Optional[int] = None
    ) -> WarrantyClaim:
        # 1. Fetch order and item
        stmt_order = select(SalesOrder).where(
            and_(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
        )
        res_order = await self.db.execute(stmt_order)
        order = res_order.scalar_one_or_none()
        if not order:
            raise SupportError(f"Order '{order_id}' not found for warranty claim.")

        stmt_item = select(OrderItem).where(
            and_(OrderItem.tenant_id == tenant_id, OrderItem.id == order_item_id, OrderItem.order_id == order_id)
        )
        res_item = await self.db.execute(stmt_item)
        item = res_item.scalar_one_or_none()
        if not item:
            raise SupportError(f"Order item '{order_item_id}' not found in order '{order_id}'.")

        # 2. Verify warranty validity window against configurable business policy
        policy_warranty_days = warranty_days if warranty_days is not None else DEFAULT_WARRANTY_DAYS
        warranty_expiry = order.created_at + timedelta(days=policy_warranty_days)
        is_expired = utc_now() > warranty_expiry

        count_stmt = select(func.count()).select_from(WarrantyClaim).where(
            WarrantyClaim.tenant_id == tenant_id
        )
        res_count = await self.db.execute(count_stmt)
        seq = (res_count.scalar() or 0) + 1
        claim_number = f"WAR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{seq:04d}"

        claim = WarrantyClaim(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            claim_number=claim_number,
            order_id=order_id,
            order_item_id=order_item_id,
            ticket_id=ticket_id,
            sku=sku,
            serial_number=serial_number,
            status="REJECTED" if is_expired else "SUBMITTED",
            warranty_valid_until=warranty_expiry,
            claim_reason=claim_reason.strip(),
            inspection_notes="Claim auto-rejected: warranty duration expired" if is_expired else None
        )
        self.db.add(claim)
        await self.db.flush()

        if is_expired:
            raise WarrantyExpiredError(
                f"Warranty for order '{order.order_number}' expired on {warranty_expiry.date()}."
            )

        return claim

    async def validate_warranty_claim(
        self,
        tenant_id: str,
        claim_id: str,
        status: str,  # VALIDATED, REJECTED, REPLACEMENT_ISSUED, REFUNDED
        inspection_notes: Optional[str] = None,
        resolved_by_user_id: Optional[str] = None
    ) -> WarrantyClaim:
        stmt = select(WarrantyClaim).where(
            and_(WarrantyClaim.tenant_id == tenant_id, WarrantyClaim.id == claim_id)
        )
        res = await self.db.execute(stmt)
        claim = res.scalar_one_or_none()
        if not claim:
            raise WarrantyClaimNotFoundError(f"Warranty claim '{claim_id}' not found.")

        claim.status = status.upper()
        claim.inspection_notes = inspection_notes
        claim.resolved_by_user_id = resolved_by_user_id
        claim.resolved_at = utc_now()
        await self.db.flush()
        return claim

    # -------------------------------------------------------------------------
    # 3. RETURN AUTHORIZATIONS (RMA) & INSPECTIONS
    # -------------------------------------------------------------------------
    async def request_rma(
        self,
        tenant_id: str,
        order_id: str,
        reason: str,
        items_data: List[Dict[str, Any]],
        destination_warehouse_id: Optional[str] = None,
        requested_action: str = "REFUND",
        ticket_id: Optional[str] = None
    ) -> ReturnAuthorization:
        """Initiates an RMA request for return of purchased goods."""
        # Validate order exists
        stmt_order = select(SalesOrder).where(
            and_(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
        )
        res_order = await self.db.execute(stmt_order)
        order = res_order.scalar_one_or_none()
        if not order:
            raise SupportError(f"Sales order '{order_id}' not found for RMA.")

        count_stmt = select(func.count()).select_from(ReturnAuthorization).where(
            ReturnAuthorization.tenant_id == tenant_id
        )
        res_count = await self.db.execute(count_stmt)
        seq = (res_count.scalar() or 0) + 1
        rma_number = f"RMA-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{seq:04d}"

        rma = ReturnAuthorization(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            rma_number=rma_number,
            order_id=order_id,
            ticket_id=ticket_id,
            status="REQUESTED",
            reason=reason.strip(),
            requested_action=requested_action.upper(),
            destination_warehouse_id=destination_warehouse_id
        )
        self.db.add(rma)
        await self.db.flush()

        for it in items_data:
            r_item = ReturnItem(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                rma_id=rma.id,
                order_item_id=it["order_item_id"],
                sku=it["sku"],
                quantity_requested=it["quantity_requested"],
                quantity_received=0,
                condition=it.get("condition", "OPENED_LIKE_NEW")
            )
            self.db.add(r_item)

        await self.db.flush()
        return await self.get_rma(tenant_id, rma.id)

    async def authorize_rma(
        self,
        tenant_id: str,
        rma_id: str,
        authorized_by_user_id: Optional[str] = None,
        destination_warehouse_id: Optional[str] = None
    ) -> ReturnAuthorization:
        rma = await self.get_rma(tenant_id, rma_id)
        if rma.status != "REQUESTED":
            raise InvalidReturnStateError(f"Cannot authorize RMA in status '{rma.status}'.")

        rma.status = "AUTHORIZED"
        rma.authorized_by_user_id = authorized_by_user_id
        rma.authorized_at = utc_now()
        if destination_warehouse_id:
            rma.destination_warehouse_id = destination_warehouse_id

        await self.db.flush()
        return await self.get_rma(tenant_id, rma.id)

    async def receive_return_items(
        self,
        tenant_id: str,
        rma_id: str,
        received_items: List[Dict[str, Any]]
    ) -> ReturnAuthorization:
        """Records physical return receipt at destination warehouse."""
        rma = await self.get_rma(tenant_id, rma_id)
        if rma.status not in ("AUTHORIZED", "REQUESTED"):
            raise InvalidReturnStateError(f"Cannot receive return in status '{rma.status}'.")

        item_map = {item.id: item for item in rma.items}
        for rec in received_items:
            item_id = rec.get("return_item_id")
            qty = rec.get("quantity_received", 0)
            cond = rec.get("condition")
            if item_id in item_map:
                item_map[item_id].quantity_received = qty
                if cond:
                    item_map[item_id].condition = cond

        rma.status = "RECEIVED"
        await self.db.flush()
        return await self.get_rma(tenant_id, rma.id)

    async def inspect_and_settle_rma(
        self,
        tenant_id: str,
        rma_id: str,
        inspection_outcome: str,  # RESTOCK, QUARANTINE, SCRAP, REJECT
        inspection_notes: str,
        inspected_by_user_id: Optional[str] = None,
        refund_amount_cents: int = 0
    ) -> ReturnAuthorization:
        """
        Executes formal return inspection, updates inventory if restocked,
        and authorizes financial refund handoff.
        """
        rma = await self.get_rma(tenant_id, rma_id)
        if rma.status not in ("RECEIVED", "AUTHORIZED"):
            raise InvalidReturnStateError(f"Cannot inspect RMA in status '{rma.status}'. Must be RECEIVED.")

        outcome = inspection_outcome.upper().strip()
        if outcome not in ("RESTOCK", "QUARANTINE", "SCRAP", "REJECT"):
            raise InvalidReturnStateError(f"Invalid inspection outcome '{outcome}'.")

        rma.inspection_outcome = outcome
        rma.inspection_notes = inspection_notes
        rma.inspected_by_user_id = inspected_by_user_id
        rma.inspected_at = utc_now()
        rma.refund_amount_cents = max(0, refund_amount_cents)

        # 1. Inventory mutation strictly based on inspection outcome
        if outcome == "RESTOCK" and rma.destination_warehouse_id:
            rma.status = "RESTOCKED"
            for item in rma.items:
                if item.quantity_received > 0:
                    # Update or create inventory item in destination warehouse
                    stmt_inv = select(InventoryItem).where(
                        and_(
                            InventoryItem.tenant_id == tenant_id,
                            InventoryItem.warehouse_id == rma.destination_warehouse_id,
                            InventoryItem.sku == item.sku
                        )
                    )
                    res_inv = await self.db.execute(stmt_inv)
                    inv = res_inv.scalar_one_or_none()
                    if not inv:
                        inv = InventoryItem(
                            id=str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            warehouse_id=rma.destination_warehouse_id,
                            sku=item.sku,
                            on_hand_quantity=0,
                            reserved_quantity=0,
                            allocated_quantity=0
                        )
                        self.db.add(inv)
                        await self.db.flush()

                    prev_on = inv.on_hand_quantity
                    inv.on_hand_quantity += item.quantity_received
                    new_on = inv.on_hand_quantity

                    # Ledger movement
                    movement = StockMovement(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        inventory_item_id=inv.id,
                        movement_type="RETURN_RESTOCK",
                        quantity_delta=item.quantity_received,
                        previous_on_hand=prev_on,
                        new_on_hand=new_on,
                        reference_type="RETURN",
                        reference_id=rma.id,
                        notes=f"RMA {rma.rma_number} Restocked after inspection: {outcome}"
                    )
                    self.db.add(movement)
        elif outcome == "REJECT":
            rma.status = "REJECTED"
            rma.refund_amount_cents = 0  # No refund for rejected returns
        else:
            # QUARANTINE or SCRAP: Goods quarantined or discarded, no available stock added
            rma.status = "INSPECTED"

        await self.db.flush()
        return await self.get_rma(tenant_id, rma.id)

    async def get_rma(self, tenant_id: str, rma_id: str) -> ReturnAuthorization:
        stmt = select(ReturnAuthorization).where(
            and_(ReturnAuthorization.tenant_id == tenant_id, ReturnAuthorization.id == rma_id)
        ).options(
            selectinload(ReturnAuthorization.items),
            selectinload(ReturnAuthorization.order),
            selectinload(ReturnAuthorization.destination_warehouse)
        )
        res = await self.db.execute(stmt)
        rma = res.scalar_one_or_none()
        if not rma:
            raise RMANotFoundError(f"RMA '{rma_id}' not found.")
        return rma

    async def list_rmas(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        order_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[ReturnAuthorization]:
        conditions = [ReturnAuthorization.tenant_id == tenant_id]
        if status:
            conditions.append(ReturnAuthorization.status == status.upper())
        if order_id:
            conditions.append(ReturnAuthorization.order_id == order_id)

        stmt = select(ReturnAuthorization).where(and_(*conditions)).order_by(
            ReturnAuthorization.created_at.desc()
        ).limit(limit).offset(offset).options(
            selectinload(ReturnAuthorization.items)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
