"""
SQLAlchemy ORM Models for Multi-Tenant Foundation, IAM, Security, and Auditing.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Integer, BigInteger, Numeric, Text, Table, UniqueConstraint, JSON, Float
)
from sqlalchemy.orm import declarative_base, relationship, synonym
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

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
    payload = Column("payload", JSON, nullable=True, default=dict)
    payload_json = synonym("payload")
    status = Column(String(20), nullable=False, default="SUCCESS")
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False)

AuditLog = AuditEvent

class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=False)
    rules = Column("rules", JSON, nullable=True, default=dict)
    rules_json = synonym("rules")
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_tenant_feature_key"),)

class Account(Base):
    __tablename__ = "accounts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    account_type = Column(String(50), nullable=False, default="CUSTOMER")  # CUSTOMER, PROSPECT, PARTNER, VENDOR
    tax_identifier = Column(String(100), nullable=True)  # ICE, VAT, EIN
    industry = Column(String(100), nullable=True)
    website = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    billing_address = Column(Text, nullable=True)
    shipping_address = Column(Text, nullable=True)
    assigned_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    assigned_user = relationship("User")
    contacts = relationship("Contact", back_populates="account")
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tenant_account_name"),)

class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
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
    account = relationship("Account", back_populates="contacts")
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
    message_class = Column(String(30), nullable=False, default="TRANSACTIONAL")  # MARKETING, TRANSACTIONAL, SERVICE, SECURITY
    recipient_identifier = Column(String(255), nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="PENDING")  # PENDING, PROCESSING, DELIVERED, FAILED, DEAD_LETTER
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_error = Column(Text, nullable=True)
    is_high_priority = Column(Boolean, nullable=False, default=False)
    claimed_by = Column(String(100), nullable=True)
    claim_token = Column(String(100), nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)


class TenantChannelIntegration(Base):
    __tablename__ = "tenant_channel_integrations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False)  # WHATSAPP, EMAIL, WEB_CHAT, VOICE_SIP
    provider_account_id = Column(String(255), nullable=True)
    provider_asset_id = Column(String(255), nullable=False)  # phone_number_id, email, SIP trunk / caller
    webhook_secret = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("channel_type", "provider_asset_id", name="uq_channel_provider_asset"),
    )

    tenant = relationship("Tenant")





class Lead(Base):
    __tablename__ = "leads"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    company_name = Column(String(200), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False, default="NEW")  # NEW, CONTACTED, QUALIFIED, CONVERTED, DISQUALIFIED
    source = Column(String(50), nullable=False, default="MANUAL")  # WEB_CHAT, WHATSAPP, EMAIL, VOICE_SIP, MANUAL, REFERRAL
    score = Column(Integer, nullable=False, default=0)
    assigned_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    converted_account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    converted_contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    converted_opportunity_id = Column(String(36), ForeignKey("opportunities.id", ondelete="SET NULL", use_alter=True, name="fk_leads_converted_opportunity_id"), nullable=True)
    notes = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    assigned_user = relationship("User")


class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    stage = Column(String(50), nullable=False, default="DISCOVERY")  # DISCOVERY, QUALIFICATION, PROPOSAL, NEGOTIATION, CLOSED_WON, CLOSED_LOST
    amount_cents = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(10), nullable=False, default="MAD")
    probability_percent = Column(Integer, nullable=False, default=20)
    expected_close_date = Column(DateTime(timezone=True), nullable=True)
    assigned_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    lost_reason = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    account = relationship("Account")
    contact = relationship("Contact")
    assigned_user = relationship("User")
    quotes = relationship("Quote", back_populates="opportunity", cascade="all, delete-orphan")


class Activity(Base):
    __tablename__ = "activities"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_type = Column(String(50), nullable=False)  # NOTE, CALL, EMAIL, MEETING, TASK
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    assigned_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    lead_id = Column(String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=True)
    opportunity_id = Column(String(36), ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True)
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    tenant = relationship("Tenant")
    assigned_user = relationship("User")


class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    product_type = Column(String(50), nullable=False, default="PHYSICAL")  # PHYSICAL, SERVICE, SUBSCRIPTION
    uom = Column(String(50), nullable=False, default="UNIT")  # UNIT, HOUR, DAY, KG, METER, BOX, PACK
    category = Column(String(100), nullable=True)
    base_price_cents = Column(BigInteger, nullable=False, default=0)
    cost_cents = Column(BigInteger, nullable=False, default=0)
    currency = Column(String(10), nullable=False, default="MAD")
    tax_rate_percent = Column(Numeric(5, 2), nullable=False, default=20.00)
    min_margin_percent = Column(Numeric(5, 2), nullable=False, default=15.00)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    variants = relationship("ProductVariant", back_populates="product", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_tenant_product_sku"),)


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    sku_variant = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    attributes_json = Column(Text, nullable=False, default="{}")
    price_adjustment_cents = Column(BigInteger, nullable=False, default=0)
    cost_adjustment_cents = Column(BigInteger, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    product = relationship("Product", back_populates="variants")
    __table_args__ = (UniqueConstraint("tenant_id", "sku_variant", name="uq_tenant_variant_sku"),)


class PriceList(Base):
    __tablename__ = "price_lists"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False)
    currency = Column(String(10), nullable=False, default="MAD")
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    items = relationship("PriceListItem", back_populates="price_list", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_tenant_pricelist_code"),)


class PriceListItem(Base):
    __tablename__ = "price_list_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    price_list_id = Column(String(36), ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=True)
    unit_price_cents = Column(BigInteger, nullable=False)
    min_quantity = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    price_list = relationship("PriceList", back_populates="items")
    product = relationship("Product")
    variant = relationship("ProductVariant")


class Quote(Base):
    __tablename__ = "quotes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    quote_number = Column(String(100), nullable=False)
    opportunity_id = Column(String(36), ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True)
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    price_list_id = Column(String(36), ForeignKey("price_lists.id", ondelete="SET NULL"), nullable=True)
    currency = Column(String(10), nullable=False, default="MAD")
    status = Column(String(50), nullable=False, default="DRAFT")  # DRAFT, PRICED, PENDING_APPROVAL, APPROVED, ISSUED, SENT, ACCEPTED, REJECTED, EXPIRED, CANCELLED
    version = Column(Integer, nullable=False, default=1)
    subtotal_cents = Column(BigInteger, nullable=False, default=0)
    discount_total_cents = Column(BigInteger, nullable=False, default=0)
    tax_total_cents = Column(BigInteger, nullable=False, default=0)
    grand_total_cents = Column(BigInteger, nullable=False, default=0)
    margin_percent = Column(Numeric(5, 2), nullable=False, default=0.00)
    requires_approval = Column(Boolean, nullable=False, default=False)
    approval_reason = Column(String(255), nullable=True)
    terms_hash = Column(String(64), nullable=False)  # Cryptographic SHA-256 of line items and pricing terms
    valid_until = Column(DateTime(timezone=True), nullable=False)
    payment_terms = Column(String(100), nullable=True, default="NET_30")
    notes = Column(Text, nullable=True)
    issued_at = Column(DateTime(timezone=True), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    opportunity = relationship("Opportunity", back_populates="quotes")
    account = relationship("Account")
    contact = relationship("Contact")
    created_by_user = relationship("User")
    items = relationship("QuoteItem", back_populates="quote", cascade="all, delete-orphan")
    approvals = relationship("QuoteApproval", back_populates="quote", cascade="all, delete-orphan")
    documents = relationship("QuoteDocument", back_populates="quote", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "quote_number", name="uq_tenant_quote_number"),)


class QuoteItem(Base):
    __tablename__ = "quote_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    quote_id = Column(String(36), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)
    sku_snapshot = Column(String(100), nullable=False)
    name_snapshot = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    uom_snapshot = Column(String(50), nullable=False)
    unit_price_cents = Column(BigInteger, nullable=False)
    unit_cost_cents = Column(BigInteger, nullable=False, default=0)
    discount_percent = Column(Numeric(5, 2), nullable=False, default=0.00)
    discount_cents = Column(BigInteger, nullable=False, default=0)
    tax_rate_percent = Column(Numeric(5, 2), nullable=False, default=20.00)
    subtotal_cents = Column(BigInteger, nullable=False)
    tax_cents = Column(BigInteger, nullable=False)
    total_cents = Column(BigInteger, nullable=False)
    margin_percent = Column(Numeric(5, 2), nullable=False, default=0.00)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    quote = relationship("Quote", back_populates="items")
    product = relationship("Product")
    variant = relationship("ProductVariant")


class QuoteApproval(Base):
    __tablename__ = "quote_approvals"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    quote_id = Column(String(36), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    quote_version = Column(Integer, nullable=False)
    terms_hash = Column(String(64), nullable=False)
    requested_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    requested_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")  # PENDING, APPROVED, REJECTED, INVALIDATED
    decided_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision_reason = Column(String(255), nullable=True)
    mfa_verified = Column(Boolean, nullable=False, default=False)
    decision_signature = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    quote = relationship("Quote", back_populates="approvals")
    requested_by = relationship("User", foreign_keys=[requested_by_user_id])
    decided_by = relationship("User", foreign_keys=[decided_by_user_id])


class QuoteDocument(Base):
    __tablename__ = "quote_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    quote_id = Column(String(36), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    quote_version = Column(Integer, nullable=False)
    document_type = Column(String(50), nullable=False, default="PRO_FORMA")  # PRO_FORMA, FORMAL_QUOTE
    document_hash = Column(String(64), nullable=False)  # Cryptographic SHA-256 of document content
    file_path = Column(String(500), nullable=False)
    content_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    quote = relationship("Quote", back_populates="documents")


# ============================================================================
# STEP 05 ENTITIES: Orders, Payments, Invoicing and Stock Reservations
# ============================================================================

class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    address_json = Column(Text, nullable=False, default="{}")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    inventory_items = relationship("InventoryItem", back_populates="warehouse", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_tenant_warehouse_code"),)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)
    sku = Column(String(100), nullable=False, index=True)
    on_hand_quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)
    allocated_quantity = Column(Integer, nullable=False, default=0)
    backorder_allowed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    warehouse = relationship("Warehouse", back_populates="inventory_items")
    product = relationship("Product")
    variant = relationship("ProductVariant")
    reservations = relationship("StockReservation", back_populates="inventory_item", cascade="all, delete-orphan")
    movements = relationship("StockMovement", back_populates="inventory_item", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "warehouse_id", "sku", name="uq_tenant_warehouse_sku"),)

    @property
    def available_to_promise(self) -> int:
        return max(0, self.on_hand_quantity - self.reserved_quantity - self.allocated_quantity)


class StockReservation(Base):
    __tablename__ = "stock_reservations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_item_id = Column(String(36), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(36), nullable=True, index=True)
    quote_id = Column(String(36), ForeignKey("quotes.id", ondelete="SET NULL"), nullable=True, index=True)
    sku = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="ACTIVE")  # ACTIVE, COMMITTED, RELEASED, EXPIRED
    reserved_until = Column(DateTime(timezone=True), nullable=False, index=True)
    idempotency_key = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    inventory_item = relationship("InventoryItem", back_populates="reservations")
    quote = relationship("Quote")


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    inventory_item_id = Column(String(36), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)
    movement_type = Column(String(50), nullable=False)  # INBOUND_RECEIPT, SALE_DEDUCTION, ADJUSTMENT, RETURN_RESTOCK, TRANSFER
    quantity_delta = Column(Integer, nullable=False)
    previous_on_hand = Column(Integer, nullable=False)
    new_on_hand = Column(Integer, nullable=False)
    reference_type = Column(String(50), nullable=False)  # ORDER, SHIPMENT, ADJUSTMENT, RETURN
    reference_id = Column(String(255), nullable=False)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    inventory_item = relationship("InventoryItem", back_populates="movements")
    created_by_user = relationship("User")


class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    order_number = Column(String(100), nullable=False)
    quote_id = Column(String(36), ForeignKey("quotes.id", ondelete="SET NULL"), nullable=True, index=True)
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), nullable=False, default="DRAFT")  # DRAFT, PENDING_PAYMENT, PAYMENT_AUTHORIZED, PAID, PROCESSING, PARTIALLY_FULFILLED, FULFILLED, CANCELLED, REFUNDED
    version = Column(Integer, nullable=False, default=1)
    currency = Column(String(10), nullable=False, default="USD")
    subtotal_cents = Column(BigInteger, nullable=False, default=0)
    discount_total_cents = Column(BigInteger, nullable=False, default=0)
    tax_total_cents = Column(BigInteger, nullable=False, default=0)
    grand_total_cents = Column(BigInteger, nullable=False, default=0)
    terms_hash = Column(String(64), nullable=False)
    payment_status = Column(String(50), nullable=False, default="UNPAID")  # UNPAID, PARTIALLY_PAID, PAID, REFUNDED
    fulfillment_status = Column(String(50), nullable=False, default="UNFULFILLED")  # UNFULFILLED, PARTIALLY_FULFILLED, FULFILLED
    shipping_address_json = Column(Text, nullable=False, default="{}")
    billing_address_json = Column(Text, nullable=False, default="{}")
    idempotency_key = Column(String(255), nullable=True, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    quote = relationship("Quote")
    account = relationship("Account")
    contact = relationship("Contact")
    created_by_user = relationship("User")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payment_intents = relationship("PaymentIntent", back_populates="order", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="order", cascade="all, delete-orphan")
    shipments = relationship("Shipment", back_populates="order", cascade="all, delete-orphan")
    support_tickets = relationship("SupportTicket", back_populates="order")
    warranty_claims = relationship("WarrantyClaim", back_populates="order")
    return_authorizations = relationship("ReturnAuthorization", back_populates="order")
    __table_args__ = (UniqueConstraint("tenant_id", "order_number", name="uq_tenant_order_number"),)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    variant_id = Column(String(36), ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True)
    sku = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    uom = Column(String(50), nullable=False, default="UNIT")
    unit_price_cents = Column(BigInteger, nullable=False)
    unit_cost_cents = Column(BigInteger, nullable=False, default=0)
    discount_percent = Column(Numeric(5, 2), nullable=False, default=0.00)
    discount_cents = Column(BigInteger, nullable=False, default=0)
    tax_rate_percent = Column(Numeric(5, 2), nullable=False, default=20.00)
    tax_cents = Column(BigInteger, nullable=False, default=0)
    subtotal_cents = Column(BigInteger, nullable=False)
    total_cents = Column(BigInteger, nullable=False)
    fulfillment_status = Column(String(50), nullable=False, default="UNFULFILLED")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    order = relationship("SalesOrder", back_populates="items")
    product = relationship("Product")
    variant = relationship("ProductVariant")


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(50), nullable=False, default="STRIPE_SANDBOX")  # STRIPE_SANDBOX, CMI_SANDBOX, BANK_TRANSFER
    provider_intent_id = Column(String(255), nullable=False)
    client_secret = Column(String(255), nullable=True)
    amount_cents = Column(BigInteger, nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    status = Column(String(50), nullable=False, default="REQUIRES_PAYMENT_METHOD")  # REQUIRES_PAYMENT_METHOD, REQUIRES_CONFIRMATION, PROCESSING, SUCCEEDED, REQUIRES_CAPTURE, CANCELLED, FAILED
    idempotency_key = Column(String(255), nullable=True, index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    order = relationship("SalesOrder", back_populates="payment_intents")
    transactions = relationship("PaymentTransaction", back_populates="payment_intent", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "provider_intent_id", name="uq_tenant_provider_intent"),)


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_intent_id = Column(String(36), ForeignKey("payment_intents.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_type = Column(String(50), nullable=False, default="CAPTURE")  # AUTHORIZATION, CAPTURE, REFUND, VOID
    amount_cents = Column(BigInteger, nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    provider_transaction_id = Column(String(255), nullable=False)
    payment_method_type = Column(String(50), nullable=False, default="CARD")
    status = Column(String(50), nullable=False, default="SUCCESS")  # SUCCESS, FAILED, PENDING
    receipt_url = Column(String(500), nullable=True)
    raw_response_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    payment_intent = relationship("PaymentIntent", back_populates="transactions")
    order = relationship("SalesOrder")


class RefundRequest(Base):
    __tablename__ = "refund_requests"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_intent_id = Column(String(36), ForeignKey("payment_intents.id", ondelete="SET NULL"), nullable=True)
    amount_cents = Column(BigInteger, nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    reason = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="REQUESTED")  # REQUESTED, APPROVED, PROCESSING, COMPLETED, REJECTED
    requested_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    provider_refund_id = Column(String(255), nullable=True)
    idempotency_key = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    order = relationship("SalesOrder")
    payment_intent = relationship("PaymentIntent")
    requested_by = relationship("User", foreign_keys=[requested_by_user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_user_id])


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_number = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="ISSUED")  # DRAFT, ISSUED, PAID, CANCELLED, REFUNDED
    currency = Column(String(10), nullable=False, default="USD")
    subtotal_cents = Column(BigInteger, nullable=False)
    discount_total_cents = Column(BigInteger, nullable=False, default=0)
    tax_total_cents = Column(BigInteger, nullable=False)
    grand_total_cents = Column(BigInteger, nullable=False)
    terms_hash = Column(String(64), nullable=False)
    invoice_hash = Column(String(64), nullable=False)
    correction_of_invoice_id = Column(String(36), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True)
    issued_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    pdf_storage_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant")
    order = relationship("SalesOrder", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    correction_of = relationship("Invoice", remote_side=[id])
    __table_args__ = (UniqueConstraint("tenant_id", "invoice_number", name="uq_tenant_invoice_number"),)


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price_cents = Column(BigInteger, nullable=False)
    discount_cents = Column(BigInteger, nullable=False, default=0)
    tax_rate_percent = Column(Numeric(5, 2), nullable=False, default=20.00)
    tax_cents = Column(BigInteger, nullable=False)
    subtotal_cents = Column(BigInteger, nullable=False)
    total_cents = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    invoice = relationship("Invoice", back_populates="items")


# =============================================================================
# Step 06: Procurement, Multi-Warehouse Operations, Logistics, Support & Scheduling
# =============================================================================

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_code = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    contact_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    payment_terms = Column(String(100), default="NET_30")
    currency = Column(String(10), default="MAD")
    address_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    products = relationship("SupplierProduct", back_populates="supplier", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="supplier")
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_code", name="uq_suppliers_tenant_code"),)


class SupplierProduct(Base):
    __tablename__ = "supplier_products"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id = Column(String(36), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    sku = Column(String(100), nullable=False)
    supplier_sku = Column(String(100), nullable=True)
    unit_cost_cents = Column(BigInteger, nullable=False)
    currency = Column(String(10), default="MAD", nullable=False)
    lead_time_days = Column(Integer, default=7, nullable=False)
    min_order_quantity = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    supplier = relationship("Supplier", back_populates="products")
    product = relationship("Product")
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "sku", name="uq_supplier_products_sku"),)


class RFQ(Base):
    __tablename__ = "rfqs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    rfq_number = Column(String(64), nullable=False)
    supplier_id = Column(String(36), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False)  # DRAFT, SENT, RESPONDED, CLOSED, CANCELLED
    deadline_date = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    supplier = relationship("Supplier")
    items = relationship("RFQItem", back_populates="rfq", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "rfq_number", name="uq_rfqs_tenant_number"),)


class RFQItem(Base):
    __tablename__ = "rfq_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    rfq_id = Column(String(36), ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    sku = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    target_unit_cost_cents = Column(BigInteger, nullable=True)
    quoted_unit_cost_cents = Column(BigInteger, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    rfq = relationship("RFQ", back_populates="items")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    po_number = Column(String(64), nullable=False)
    supplier_id = Column(String(36), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    rfq_id = Column(String(36), ForeignKey("rfqs.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="DRAFT", nullable=False)  # DRAFT, APPROVED, ISSUED, PARTIALLY_RECEIVED, RECEIVED, CLOSED, CANCELLED
    version = Column(Integer, default=1, nullable=False)
    currency = Column(String(10), default="MAD", nullable=False)
    subtotal_cents = Column(BigInteger, default=0, nullable=False)
    tax_cents = Column(BigInteger, default=0, nullable=False)
    grand_total_cents = Column(BigInteger, default=0, nullable=False)
    payment_terms = Column(String(100), default="NET_30")
    notes = Column(Text, nullable=True)
    approved_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    issued_at = Column(DateTime(timezone=True), nullable=True)
    expected_delivery_date = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    supplier = relationship("Supplier", back_populates="purchase_orders")
    warehouse = relationship("Warehouse")
    rfq = relationship("RFQ")
    items = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan")
    goods_receipts = relationship("GoodsReceipt", back_populates="purchase_order")
    __table_args__ = (UniqueConstraint("tenant_id", "po_number", name="uq_purchase_orders_tenant_number"),)


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    sku = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    quantity_ordered = Column(Integer, nullable=False)
    quantity_received = Column(Integer, default=0, nullable=False)
    unit_cost_cents = Column(BigInteger, nullable=False)
    subtotal_cents = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    purchase_order = relationship("PurchaseOrder", back_populates="items")


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    receipt_number = Column(String(64), nullable=False)
    purchase_order_id = Column(String(36), ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    received_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    carrier_name = Column(String(100), nullable=True)
    tracking_reference = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    purchase_order = relationship("PurchaseOrder", back_populates="goods_receipts")
    warehouse = relationship("Warehouse")
    items = relationship("GoodsReceiptItem", back_populates="goods_receipt", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "receipt_number", name="uq_goods_receipts_tenant_number"),)


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    goods_receipt_id = Column(String(36), ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    po_item_id = Column(String(36), ForeignKey("purchase_order_items.id", ondelete="RESTRICT"), nullable=False)
    sku = Column(String(100), nullable=False)
    quantity_received = Column(Integer, nullable=False)
    quantity_rejected = Column(Integer, default=0, nullable=False)
    rejection_reason = Column(String(255), nullable=True)
    lot_number = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    goods_receipt = relationship("GoodsReceipt", back_populates="items")
    po_item = relationship("PurchaseOrderItem")


class StockTransfer(Base):
    __tablename__ = "stock_transfers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    transfer_number = Column(String(64), nullable=False)
    source_warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    destination_warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(30), default="DRAFT", nullable=False)  # DRAFT, REQUESTED, APPROVED, IN_TRANSIT, RECEIVED, CANCELLED
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    shipped_at = Column(DateTime(timezone=True), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    source_warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id])
    destination_warehouse = relationship("Warehouse", foreign_keys=[destination_warehouse_id])
    items = relationship("StockTransferItem", back_populates="transfer", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "transfer_number", name="uq_stock_transfers_tenant_number"),)


class StockTransferItem(Base):
    __tablename__ = "stock_transfer_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    transfer_id = Column(String(36), ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(100), nullable=False)
    quantity_requested = Column(Integer, nullable=False)
    quantity_shipped = Column(Integer, default=0, nullable=False)
    quantity_received = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    transfer = relationship("StockTransfer", back_populates="items")


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_number = Column(String(64), nullable=False)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    carrier_code = Column(String(50), nullable=False)
    carrier_service = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    status = Column(String(30), default="CREATED", nullable=False)  # CREATED, PICKING, PACKED, SHIPPED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, FAILED, RETURNED, CANCELLED
    shipping_address_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    delivery_contact_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    shipping_label_url = Column(String(500), nullable=True)
    estimated_delivery_at = Column(DateTime(timezone=True), nullable=True)
    shipped_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    failure_reason = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    order = relationship("SalesOrder", back_populates="shipments")
    warehouse = relationship("Warehouse")
    items = relationship("ShipmentItem", back_populates="shipment", cascade="all, delete-orphan")
    tracking_events = relationship("ShipmentTrackingEvent", back_populates="shipment", cascade="all, delete-orphan")
    delivery_proof = relationship("DeliveryProof", back_populates="shipment", uselist=False, cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "shipment_number", name="uq_shipments_tenant_number"),)


class ShipmentItem(Base):
    __tablename__ = "shipment_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id = Column(String(36), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False)
    sku = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    shipment = relationship("Shipment", back_populates="items")
    order_item = relationship("OrderItem")


class ShipmentTrackingEvent(Base):
    __tablename__ = "shipment_tracking_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False)
    event_timestamp = Column(DateTime(timezone=True), nullable=False)
    location = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    raw_payload_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    shipment = relationship("Shipment", back_populates="tracking_events")


class DeliveryProof(Base):
    __tablename__ = "delivery_proofs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_id = Column(String(36), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_name = Column(String(255), nullable=False)
    signature_image_url = Column(String(500), nullable=True)
    photo_url = Column(String(500), nullable=True)
    signed_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    location_coordinates = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    shipment = relationship("Shipment", back_populates="delivery_proof")
    __table_args__ = (UniqueConstraint("tenant_id", "shipment_id", name="uq_delivery_proof_shipment"),)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_number = Column(String(64), nullable=False)
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True)
    priority = Column(String(20), default="MEDIUM", nullable=False)  # LOW, MEDIUM, HIGH, URGENT
    category = Column(String(50), default="GENERAL", nullable=False)  # SHIPPING_DELAY, DAMAGED_GOODS, WARRANTY_CLAIM, BILLING, GENERAL
    status = Column(String(30), default="OPEN", nullable=False)  # OPEN, IN_PROGRESS, PENDING_CUSTOMER, RESOLVED, CLOSED
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    assigned_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    order = relationship("SalesOrder", back_populates="support_tickets")
    account = relationship("Account")
    contact = relationship("Contact")
    assigned_user = relationship("User")
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "ticket_number", name="uq_support_tickets_tenant_number"),)


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id = Column(String(36), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_type = Column(String(20), nullable=False)  # CUSTOMER, AGENT, SYSTEM
    sender_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message_text = Column(Text, nullable=False)
    attachments_json = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    ticket = relationship("SupportTicket", back_populates="messages")


class WarrantyClaim(Base):
    __tablename__ = "warranty_claims"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_number = Column(String(64), nullable=False)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False)
    order_item_id = Column(String(36), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False)
    ticket_id = Column(String(36), ForeignKey("support_tickets.id", ondelete="SET NULL"), nullable=True)
    sku = Column(String(100), nullable=False)
    serial_number = Column(String(100), nullable=True)
    status = Column(String(30), default="SUBMITTED", nullable=False)  # SUBMITTED, VALIDATED, REJECTED, REPLACEMENT_ISSUED, REFUNDED
    warranty_valid_until = Column(DateTime(timezone=True), nullable=False)
    claim_reason = Column(Text, nullable=False)
    inspection_notes = Column(Text, nullable=True)
    resolved_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    order = relationship("SalesOrder", back_populates="warranty_claims")
    order_item = relationship("OrderItem")
    ticket = relationship("SupportTicket")
    __table_args__ = (UniqueConstraint("tenant_id", "claim_number", name="uq_warranty_claims_tenant_number"),)


class ReturnAuthorization(Base):
    __tablename__ = "return_authorizations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    rma_number = Column(String(64), nullable=False)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False)
    ticket_id = Column(String(36), ForeignKey("support_tickets.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="REQUESTED", nullable=False)  # REQUESTED, AUTHORIZED, RECEIVED, INSPECTED, RESTOCKED, REJECTED, CANCELLED
    reason = Column(Text, nullable=False)
    requested_action = Column(String(30), default="REFUND", nullable=False)  # REFUND, REPLACEMENT, STORE_CREDIT
    inspection_outcome = Column(String(30), nullable=True)  # RESTOCK, QUARANTINE, SCRAP, REJECT
    inspection_notes = Column(Text, nullable=True)
    refund_amount_cents = Column(BigInteger, default=0, nullable=False)
    destination_warehouse_id = Column(String(36), ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True)
    authorized_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    inspected_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    authorized_at = Column(DateTime(timezone=True), nullable=True)
    inspected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    order = relationship("SalesOrder", back_populates="return_authorizations")
    ticket = relationship("SupportTicket")
    destination_warehouse = relationship("Warehouse")
    items = relationship("ReturnItem", back_populates="rma", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("tenant_id", "rma_number", name="uq_rma_tenant_number"),)


class ReturnItem(Base):
    __tablename__ = "return_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    rma_id = Column(String(36), ForeignKey("return_authorizations.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id = Column(String(36), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False)
    sku = Column(String(100), nullable=False)
    quantity_requested = Column(Integer, nullable=False)
    quantity_received = Column(Integer, default=0, nullable=False)
    condition = Column(String(50), nullable=True)  # UNOPENED, OPENED_LIKE_NEW, DAMAGED, DEFECTIVE
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    rma = relationship("ReturnAuthorization", back_populates="items")
    order_item = relationship("OrderItem")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_number = Column(String(64), nullable=False)
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    order_id = Column(String(36), ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True)
    service_type = Column(String(50), nullable=False)  # SALES_DEMO, ON_SITE_INSTALLATION, HARDWARE_SUPPORT, DELIVERY_SLOT
    status = Column(String(30), default="REQUESTED", nullable=False)  # REQUESTED, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED, RESCHEDULED
    staff_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    location_type = Column(String(30), default="VIDEO_CALL", nullable=False)  # VIDEO_CALL, ON_SITE, PHONE
    location_details = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    account = relationship("Account")
    contact = relationship("Contact")
    order = relationship("SalesOrder")
    staff_user = relationship("User")
    __table_args__ = (UniqueConstraint("tenant_id", "booking_number", name="uq_appointments_tenant_number"),)


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    channel_type = Column(String(32), default="WEBRTC", nullable=False)  # WEBRTC, SIP_PSTN, WEB_VOICE
    voice_mode = Column(String(32), default="CUSTOMER", nullable=False)   # CUSTOMER, MANAGER
    caller_identifier = Column(String(255), nullable=True, index=True)
    customer_account_id = Column(String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    customer_contact_id = Column(String(36), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    manager_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(32), default="INITIATED", nullable=False)      # INITIATED, ACTIVE, PAUSED, TRANSFERRED, COMPLETED, FAILED
    language = Column(String(16), default="fr-FR", nullable=False)        # fr-FR, en-US, ar-MA, ary-Arab, ary-Latn
    is_caller_verified = Column(Boolean, default=False, nullable=False)
    recording_consent_given = Column(Boolean, default=False, nullable=False)
    disclosure_played = Column(Boolean, default=False, nullable=False)
    turns_count = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    customer_account = relationship("Account")
    customer_contact = relationship("Contact")
    manager_user = relationship("User")
    transcripts = relationship("VoiceTranscript", back_populates="session", cascade="all, delete-orphan", order_by="VoiceTranscript.turn_index")
    recordings = relationship("VoiceRecording", back_populates="session", cascade="all, delete-orphan")


class VoiceTranscript(Base):
    __tablename__ = "voice_transcripts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(100), ForeignKey("voice_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    turn_index = Column(Integer, default=0, nullable=False)
    speaker_type = Column(String(32), nullable=False)  # USER, AGENT, SYSTEM
    raw_text = Column(Text, nullable=False)
    redacted_text = Column(Text, nullable=False)
    language = Column(String(16), default="fr-FR", nullable=False)
    latency_ms = Column(Integer, default=0, nullable=True)
    is_barge_in = Column(Boolean, default=False, nullable=False)
    metadata_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    session = relationship("VoiceSession", back_populates="transcripts")


class VoiceRecording(Base):
    __tablename__ = "voice_recordings"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(100), ForeignKey("voice_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    storage_path = Column(String(512), nullable=False)
    duration_seconds = Column(Integer, default=0, nullable=False)
    file_size_bytes = Column(Integer, default=0, nullable=False)
    mime_type = Column(String(64), default="audio/wav", nullable=False)
    encryption_algorithm = Column(String(32), default="AES-256-GCM", nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    session = relationship("VoiceSession", back_populates="recordings")


# ============================================================================
# Step 07: Workflows, Notifications, and Automations Entities
# ============================================================================

class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_type = Column(String(100), nullable=False)
    correlation_id = Column(String(100), nullable=False, index=True)
    idempotency_key = Column(String(255), nullable=False, index=True)
    status = Column(String(30), default="RUNNING", nullable=False, index=True)
    current_step = Column(String(100), nullable=True)
    payload_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    result_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=True)
    error_details = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    step_logs = relationship("WorkflowStepLog", back_populates="workflow", cascade="all, delete-orphan")

    @property
    def error_message(self) -> Optional[str]:
        return self.error_details

    @error_message.setter
    def error_message(self, val: Optional[str]):
        self.error_details = val

    @property
    def context_payload(self) -> Dict[str, Any]:
        return {"step_outputs": self.result_json or {}}

    @context_payload.setter
    def context_payload(self, val: Dict[str, Any]):
        self.result_json = val.get("step_outputs", val)


class WorkflowStepLog(Base):
    __tablename__ = "workflow_step_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workflow_id = Column(String(36), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    step_name = Column(String(100), nullable=False)
    step_type = Column(String(30), default="ACTION", nullable=False)  # ACTION, COMPENSATION
    status = Column(String(30), default="STARTED", nullable=False)    # STARTED, COMPLETED, FAILED
    input_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=True)
    output_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    workflow = relationship("WorkflowExecution", back_populates="step_logs")

    @property
    def output_payload(self) -> Optional[Dict[str, Any]]:
        return self.output_json

    @output_payload.setter
    def output_payload(self, val: Optional[Dict[str, Any]]):
        self.output_json = val

    @property
    def execution_duration_ms(self) -> float:
        return float(self.duration_ms)

    @execution_duration_ms.setter
    def execution_duration_ms(self, val: float):
        self.duration_ms = int(val)


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    template_code = Column(String(100), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False)  # EMAIL, WHATSAPP, IN_APP
    message_class = Column(String(30), default="TRANSACTIONAL", nullable=False)  # MARKETING, TRANSACTIONAL, SERVICE, SECURITY
    language = Column(String(10), default="fr-FR", nullable=False)
    subject_template = Column(String(255), nullable=True)
    body_template = Column(Text, nullable=False)
    variables_json = Column(JSON().with_variant(JSONB, "postgresql"), default=list, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    logs = relationship("NotificationLog", back_populates="template")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id = Column(String(36), ForeignKey("notification_templates.id", ondelete="SET NULL"), nullable=True)
    recipient_identifier = Column(String(255), nullable=False, index=True)
    channel_type = Column(String(30), nullable=False)
    message_class = Column(String(30), default="TRANSACTIONAL", nullable=False)
    subject = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    status = Column(String(30), default="PENDING", nullable=False, index=True)  # PENDING, SENT, DELIVERED, FAILED, CANCELLED
    error_reason = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    metadata_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    template = relationship("NotificationTemplate", back_populates="logs")


class AutomationRule(Base):
    __tablename__ = "automation_rules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    trigger_event = Column(String(100), nullable=False, index=True)
    condition_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=True)
    action_type = Column(String(100), nullable=False)
    action_config_json = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False, default="TEXT")
    document_hash = Column(String(64), nullable=False, index=True)
    acl_roles = Column(ARRAY(String).with_variant(JSON, "sqlite"), nullable=False, default=list)
    status = Column(String(50), nullable=False, default="INDEXED", index=True)  # INDEXED, TOMBSTONED, POISON_DETECTED
    poison_reason = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    sanitized_content = Column(Text, nullable=False)
    token_count = Column(Integer, default=0, nullable=False)
    embedding_vector = Column(ARRAY(Float).with_variant(JSON, "sqlite"), default=list, nullable=False)
    metadata_json = Column("metadata", JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    document = relationship("KnowledgeDocument", back_populates="chunks")


class ModelExecutionLog(Base):
    __tablename__ = "model_execution_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_id = Column(String(64), nullable=True, index=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)
    prompt_template_id = Column(String(100), nullable=True)
    prompt_hash = Column(String(64), nullable=True)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    estimated_cost_usd = Column(Numeric(10, 6), default=0.0, nullable=False)
    latency_ms = Column(Numeric(10, 2), default=0.0, nullable=False)
    ttft_ms = Column(Numeric(10, 2), default=0.0, nullable=False)
    pii_redacted_count = Column(Integer, default=0, nullable=False)
    status = Column(String(50), default="SUCCESS", nullable=False)  # SUCCESS, FALLBACK, TIMEOUT, ERROR, BLOCKED
    error_message = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

