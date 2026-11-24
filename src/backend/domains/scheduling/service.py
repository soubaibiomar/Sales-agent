"""
Appointment Scheduling & Calendar Availability Domain Service.
Double-booking protection, calendar slot calculation, and concurrency conflict guards.
(Controls 05, 06, 07, 16, 21, 22, 57, 58)
Step 06: Sprint 3 - Operate
"""
import uuid
import asyncio
from datetime import datetime, timezone, timedelta, time
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.models.entities import Appointment, User, Account, Contact, SalesOrder


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SchedulingError(Exception):
    pass


class AppointmentNotFoundError(SchedulingError):
    pass


class BookingConflictError(SchedulingError):
    """Raised when an appointment slot is already occupied for the requested staff member."""
    pass


class InvalidAppointmentStateError(SchedulingError):
    pass


# Application-level lock to prevent concurrency races during slot validation
_staff_booking_locks: Dict[str, asyncio.Lock] = {}


class SchedulingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # 1. APPOINTMENT BOOKING WITH CONFLICT PROTECTION
    # -------------------------------------------------------------------------
    async def book_appointment(
        self,
        tenant_id: str,
        service_type: str,
        start_time: datetime,
        end_time: datetime,
        staff_user_id: Optional[str] = None,
        location_type: str = "VIDEO_CALL",
        location_details: Optional[str] = None,
        notes: Optional[str] = None,
        account_id: Optional[str] = None,
        contact_id: Optional[str] = None,
        order_id: Optional[str] = None
    ) -> Appointment:
        """
        Books an appointment while ensuring no temporal conflict exists for the staff user.
        Uses concurrency locking to prevent booking race conditions.
        """
        if end_time <= start_time:
            raise SchedulingError("Appointment end_time must be strictly after start_time.")

        lock_key = f"{tenant_id}:{staff_user_id or 'unassigned'}"
        if lock_key not in _staff_booking_locks:
            _staff_booking_locks[lock_key] = asyncio.Lock()

        async with _staff_booking_locks[lock_key]:
            # Acquire database-level transaction lock on PostgreSQL to guarantee multi-worker safety
            if staff_user_id and self.db.get_bind().dialect.name == "postgresql":
                # Deterministic key: Python's hash() is randomised per process, so the
                # previous key never collided across workers. The appointments exclusion
                # constraint (migration 012) is the final guard either way.
                import hashlib
                lock_id = int.from_bytes(
                    hashlib.sha256(f"staff_booking:{tenant_id}:{staff_user_id}".encode()).digest()[:8], "big", signed=True
                )
                await self.db.execute(select(func.pg_advisory_xact_lock(lock_id)))

            # Check overlap if staff assigned
            if staff_user_id:
                has_conflict = await self._check_temporal_conflict(
                    tenant_id=tenant_id,
                    staff_user_id=staff_user_id,
                    start_time=start_time,
                    end_time=end_time
                )
                if has_conflict:
                    raise BookingConflictError(
                        f"Staff member '{staff_user_id}' already has a conflicting booking during the requested time window."
                    )

            # Generate booking sequence
            count_stmt = select(func.count()).select_from(Appointment).where(
                Appointment.tenant_id == tenant_id
            )
            res_count = await self.db.execute(count_stmt)
            seq = (res_count.scalar() or 0) + 1
            booking_number = f"APT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{seq:04d}"

            appointment = Appointment(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                booking_number=booking_number,
                account_id=account_id,
                contact_id=contact_id,
                order_id=order_id,
                service_type=service_type.upper(),
                status="CONFIRMED" if staff_user_id else "REQUESTED",
                staff_user_id=staff_user_id,
                start_time=start_time,
                end_time=end_time,
                location_type=location_type.upper(),
                location_details=location_details,
                notes=notes
            )
            self.db.add(appointment)
            await self.db.flush()
            return appointment

    async def _check_temporal_conflict(
        self,
        tenant_id: str,
        staff_user_id: str,
        start_time: datetime,
        end_time: datetime,
        exclude_appointment_id: Optional[str] = None
    ) -> bool:
        """
        Returns True if an overlapping active appointment exists for this staff member.
        Active states: REQUESTED, CONFIRMED, IN_PROGRESS, RESCHEDULED.
        Interval overlap: (A_start < B_end) AND (A_end > B_start).
        """
        conditions = [
            Appointment.tenant_id == tenant_id,
            Appointment.staff_user_id == staff_user_id,
            Appointment.status.in_(["REQUESTED", "CONFIRMED", "IN_PROGRESS", "RESCHEDULED"]),
            Appointment.start_time < end_time,
            Appointment.end_time > start_time
        ]
        if exclude_appointment_id:
            conditions.append(Appointment.id != exclude_appointment_id)

        stmt = select(func.count()).select_from(Appointment).where(and_(*conditions))
        res = await self.db.execute(stmt)
        count = res.scalar() or 0
        return count > 0

    # -------------------------------------------------------------------------
    # 2. CALENDAR AVAILABILITY SLOTS
    # -------------------------------------------------------------------------
    async def get_available_slots(
        self,
        tenant_id: str,
        target_date: datetime,
        staff_user_id: Optional[str] = None,
        duration_minutes: int = 30,
        start_hour: int = 9,
        end_hour: int = 18
    ) -> List[Dict[str, Any]]:
        """
        Generates available booking slots on a given date during business hours,
        filtering out overlapping appointments.
        """
        day_start = datetime(
            target_date.year, target_date.month, target_date.day,
            start_hour, 0, 0, tzinfo=timezone.utc
        )
        day_end = datetime(
            target_date.year, target_date.month, target_date.day,
            end_hour, 0, 0, tzinfo=timezone.utc
        )

        # Fetch existing appointments for the day
        conditions = [
            Appointment.tenant_id == tenant_id,
            Appointment.status.in_(["REQUESTED", "CONFIRMED", "IN_PROGRESS", "RESCHEDULED"]),
            Appointment.start_time < day_end,
            Appointment.end_time > day_start
        ]
        if staff_user_id:
            conditions.append(Appointment.staff_user_id == staff_user_id)

        stmt = select(Appointment).where(and_(*conditions))
        res = await self.db.execute(stmt)
        existing_appointments = list(res.scalars().all())

        available_slots = []
        current = day_start
        delta = timedelta(minutes=duration_minutes)

        while current + delta <= day_end:
            slot_end = current + delta
            # Check overlap against any existing appointment
            overlap = any(
                (apt.start_time < slot_end and apt.end_time > current)
                for apt in existing_appointments
            )
            available_slots.append({
                "start_time": current.isoformat(),
                "end_time": slot_end.isoformat(),
                "duration_minutes": duration_minutes,
                "is_available": not overlap
            })
            current += delta

        return available_slots

    # -------------------------------------------------------------------------
    # 3. STATUS TRANSITIONS & RESCHEDULING
    # -------------------------------------------------------------------------
    async def reschedule_appointment(
        self,
        tenant_id: str,
        appointment_id: str,
        new_start_time: datetime,
        new_end_time: datetime
    ) -> Appointment:
        apt = await self.get_appointment(tenant_id, appointment_id)
        if apt.status in ("CANCELLED", "COMPLETED"):
            raise InvalidAppointmentStateError(f"Cannot reschedule an appointment in status '{apt.status}'.")

        if apt.staff_user_id:
            conflict = await self._check_temporal_conflict(
                tenant_id=tenant_id,
                staff_user_id=apt.staff_user_id,
                start_time=new_start_time,
                end_time=new_end_time,
                exclude_appointment_id=apt.id
            )
            if conflict:
                raise BookingConflictError("The requested reschedule slot conflicts with an existing booking.")

        apt.start_time = new_start_time
        apt.end_time = new_end_time
        apt.status = "RESCHEDULED"
        await self.db.flush()
        return apt

    async def update_status(
        self,
        tenant_id: str,
        appointment_id: str,
        status: str,
        notes: Optional[str] = None
    ) -> Appointment:
        apt = await self.get_appointment(tenant_id, appointment_id)
        status_upper = status.upper().strip()
        if status_upper not in ("REQUESTED", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "RESCHEDULED"):
            raise InvalidAppointmentStateError(f"Invalid appointment status '{status_upper}'.")

        apt.status = status_upper
        if notes:
            apt.notes = notes
        await self.db.flush()
        return apt

    async def get_appointment(self, tenant_id: str, appointment_id: str) -> Appointment:
        stmt = select(Appointment).where(
            and_(Appointment.tenant_id == tenant_id, Appointment.id == appointment_id)
        ).options(
            selectinload(Appointment.staff_user),
            selectinload(Appointment.account),
            selectinload(Appointment.contact)
        )
        res = await self.db.execute(stmt)
        apt = res.scalar_one_or_none()
        if not apt:
            raise AppointmentNotFoundError(f"Appointment '{appointment_id}' not found.")
        return apt

    async def list_appointments(
        self,
        tenant_id: str,
        staff_user_id: Optional[str] = None,
        status: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Appointment]:
        conditions = [Appointment.tenant_id == tenant_id]
        if staff_user_id:
            conditions.append(Appointment.staff_user_id == staff_user_id)
        if status:
            conditions.append(Appointment.status == status.upper())
        if from_date:
            conditions.append(Appointment.start_time >= from_date)
        if to_date:
            conditions.append(Appointment.end_time <= to_date)

        stmt = select(Appointment).where(and_(*conditions)).order_by(
            Appointment.start_time.asc()
        ).limit(limit).offset(offset)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
