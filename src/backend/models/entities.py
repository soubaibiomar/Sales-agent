"""
SQLAlchemy ORM Models for Multi-Tenant Foundation, IAM, Security, and Auditing.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Integer, BigInteger, Numeric, Text, Table, UniqueConstraint, JSON
)
from sqlalchemy.orm import declarative_base, relationship, synonym
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
    payload = Column("payload", JSON, nullable=True, default=dict)
    payload_json = synonym("payload")
    status = Column(String(20), nullable=False, default="SUCCESS")
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False)

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
    converted_opportunity_id = Column(String(36), ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True)
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
