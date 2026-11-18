"""
Appointments & Booking Pydantic Schemas.
Step 06: Sprint 3 - Operate
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class AppointmentCreateRequest(BaseModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    order_id: Optional[str] = None
    service_type: str = Field(..., max_length=50)  # SALES_DEMO, ON_SITE_INSTALLATION, HARDWARE_SUPPORT, DELIVERY_SLOT
    staff_user_id: Optional[str] = None
    start_time: datetime
    end_time: datetime
    location_type: str = Field("VIDEO_CALL", max_length=30)  # VIDEO_CALL, ON_SITE, PHONE
    location_details: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class AppointmentUpdateRequest(BaseModel):
    status: Optional[str] = None  # REQUESTED, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED, RESCHEDULED
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    staff_user_id: Optional[str] = None
    location_details: Optional[str] = None
    notes: Optional[str] = None


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    booking_number: str
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    order_id: Optional[str] = None
    service_type: str
    status: str
    staff_user_id: Optional[str] = None
    start_time: datetime
    end_time: datetime
    location_type: str
    location_details: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CalendarAvailabilityRequest(BaseModel):
    staff_user_id: Optional[str] = None
    start_date: datetime
    end_date: datetime
    service_type: Optional[str] = None


class CalendarSlotResponse(BaseModel):
    staff_user_id: str
    start_time: datetime
    end_time: datetime
    is_available: bool
