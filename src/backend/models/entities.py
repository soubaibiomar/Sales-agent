"""
SQLAlchemy ORM Models for Multi-Tenant Foundation, IAM, Security, and Auditing.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Integer, Text, Table, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def generate_uuid() -> str:
    return str(uuid.uuid4())

# Association table for Role <-> Permission
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String(36), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    tier = Column(String(50), nullable=False, default="standard")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    sites = relationship("OrganizationSite", back_populates="tenant", cascade="all, delete-orphan")

class OrganizationSite(Base):
    __tablename__ = "organization_sites"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False)
    timezone = Column(String(50), nullable=False, default="Africa/Casablanca")
    currency = Column(String(10), nullable=False, default="MAD")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    tenant = relationship("Tenant", back_populates="sites")
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_site_tenant_code"),)

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    mfa_secret = Column(String(255), nullable=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant", back_populates="users")
    user_roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)

class Role(Base):
    __tablename__ = "roles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_privileged = Column(Boolean, nullable=False, default=False)

    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

class Permission(Base):
    __tablename__ = "permissions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    domain = Column(String(50), nullable=False)

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True, index=True)

    user = relationship("User", back_populates="user_roles")
    role = relationship("Role")

class SessionRevocation(Base):
    __tablename__ = "session_revocations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    token_jti = Column(String(255), unique=True, nullable=False, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    revoked_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(String(255), nullable=False, default="logout")

class AuditEvent(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(String(36), nullable=True)
    event_type = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(255), nullable=True)
    action = Column(String(50), nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True, default="{}")
    status = Column(String(20), nullable=False, default="SUCCESS")
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False)

class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=False)
    rules_json = Column(Text, nullable=True, default="{}")
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_tenant_feature_key"),)

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    display_name = Column(String(200), nullable=False)
    primary_email = Column(String(255), nullable=True)
    primary_phone = Column(String(50), nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    metadata_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    identities = relationship("ChannelIdentity", back_populates="contact", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="contact", cascade="all, delete-orphan")

class ChannelIdentity(Base):
    __tablename__ = "channel_identities"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False)  # WEB_CHAT, WHATSAPP, EMAIL, VOICE_SIP
    identifier = Column(String(255), nullable=False)   # Phone number, email address, or web session UUID
    is_opted_out = Column(Boolean, nullable=False, default=False)
    opt_out_at = Column(DateTime(timezone=True), nullable=True)
    opt_out_reason = Column(String(255), nullable=True)
    consent_given_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    metadata_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    contact = relationship("Contact", back_populates="identities")
    __table_args__ = (UniqueConstraint("tenant_id", "channel_type", "identifier", name="uq_tenant_channel_identifier"),)

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False)
    channel_identifier = Column(String(255), nullable=False)
    status = Column(String(30), nullable=False, default="BOT_ACTIVE")  # BOT_ACTIVE, HUMAN_PENDING, HUMAN_ACTIVE, CLOSED
    assigned_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    is_ai_silenced = Column(Boolean, nullable=False, default=False)
    unread_count = Column(Integer, nullable=False, default=0)
    last_message_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    metadata_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    contact = relationship("Contact", back_populates="conversations")
    assigned_user = relationship("User")
    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan")

class InboundRawEvent(Base):
    __tablename__ = "inbound_raw_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False)
    provider_event_id = Column(String(255), nullable=False)
    payload_json = Column(Text, nullable=False)
    signature_verified = Column(Boolean, nullable=False, default=True)
    processing_status = Column(String(30), nullable=False, default="PENDING")  # PENDING, PROCESSED, FAILED, DUPLICATE
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "channel_type", "provider_event_id", name="uq_tenant_channel_provider_event"),)

class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_type = Column(String(20), nullable=False)  # CUSTOMER, AGENT, AI_BOT, SYSTEM
    sender_id = Column(String(36), nullable=True)
    content = Column(Text, nullable=False)
    content_redacted = Column(Text, nullable=True)
    event_type = Column(String(30), nullable=False, default="MESSAGE")  # MESSAGE, STATUS_CHANGE, HANDOFF, CONSENT_STOP, ATTACHMENT
    conversation_version = Column(Integer, nullable=False, default=1)
    attachments_json = Column(Text, nullable=True, default="[]")
    metadata_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")
    attachments = relationship("MessageAttachment", back_populates="message", cascade="all, delete-orphan")

class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    message_id = Column(String(36), ForeignKey("conversation_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    storage_path = Column(String(500), nullable=False)
    is_safe = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    message = relationship("ConversationMessage", back_populates="attachments")

class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False)  # DISPATCH_MESSAGE, NOTIFICATION, SAFETY_ALERT
    channel_type = Column(String(30), nullable=False)  # WHATSAPP, EMAIL, WEB_CHAT, VOICE_SIP
    recipient_identifier = Column(String(255), nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="PENDING")  # PENDING, PROCESSING, DELIVERED, FAILED, DEAD_LETTER
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_error = Column(Text, nullable=True)
    is_high_priority = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)


