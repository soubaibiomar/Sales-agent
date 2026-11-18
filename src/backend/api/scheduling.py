"""
Appointment Scheduling & Calendar Availability REST API Endpoints.
Double-booking protection, calendar slot availability, and booking lifecycle.
(Controls 05, 06, 07, 16, 21, 22, 57, 58)
Step 06: Sprint 3 - Operate
"""
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.scheduling.service import (
    SchedulingService, SchedulingError, AppointmentNotFoundError,
    BookingConflictError, InvalidAppointmentStateError
)
from src.backend.schemas.scheduling import (
    AppointmentCreateRequest, AppointmentUpdateRequest, AppointmentResponse,
    CalendarSlotResponse
)

router = APIRouter(prefix="/scheduling", tags=["Scheduling & Bookings"])


@router.post("/appointments", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def book_appointment(
    req: AppointmentCreateRequest,
    ctx: SecurityContext = Depends(require_permission("scheduling:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SchedulingService(db)
    try:
        return await service.book_appointment(
            tenant_id=ctx.tenant_id,
            service_type=req.service_type,
            start_time=req.start_time,
            end_time=req.end_time,
            staff_user_id=req.staff_user_id,
            location_type=req.location_type,
            location_details=req.location_details,
            notes=req.notes,
            account_id=req.account_id,
            contact_id=req.contact_id,
            order_id=req.order_id
        )
    except BookingConflictError as e:
        # Invariant: Concurrency conflict / double booking rejected
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except SchedulingError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/appointments", response_model=List[AppointmentResponse])
async def list_appointments(
    staff_user_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("scheduling:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SchedulingService(db)
    return await service.list_appointments(
        ctx.tenant_id,
        staff_user_id=staff_user_id,
        status=status_filter,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset
    )


@router.get("/appointments/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: str,
    ctx: SecurityContext = Depends(require_permission("scheduling:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SchedulingService(db)
    try:
        return await service.get_appointment(ctx.tenant_id, appointment_id)
    except AppointmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/appointments/{appointment_id}/status", response_model=AppointmentResponse)
async def update_appointment_status(
    appointment_id: str,
    req: AppointmentUpdateRequest,
    ctx: SecurityContext = Depends(require_permission("scheduling:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SchedulingService(db)
    try:
        new_status = req.status or "CONFIRMED"
        return await service.update_status(
            ctx.tenant_id, appointment_id, status=new_status, notes=req.notes
        )
    except AppointmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidAppointmentStateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment(
    appointment_id: str,
    new_start_time: datetime = Query(...),
    new_end_time: datetime = Query(...),
    ctx: SecurityContext = Depends(require_permission("scheduling:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SchedulingService(db)
    try:
        return await service.reschedule_appointment(
            ctx.tenant_id, appointment_id, new_start_time=new_start_time, new_end_time=new_end_time
        )
    except AppointmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BookingConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (InvalidAppointmentStateError, SchedulingError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/availability/slots")
async def get_available_slots(
    date: datetime = Query(...),
    staff_user_id: Optional[str] = None,
    duration_minutes: int = Query(30, ge=15, le=120),
    ctx: SecurityContext = Depends(require_permission("scheduling:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = SchedulingService(db)
    slots = await service.get_available_slots(
        tenant_id=ctx.tenant_id,
        target_date=date,
        staff_user_id=staff_user_id,
        duration_minutes=duration_minutes
    )
    return slots
