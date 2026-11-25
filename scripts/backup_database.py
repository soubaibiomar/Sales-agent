"""
LEGACY partial export (kept for its Step 02 tests). NOT a disaster-recovery backup:
it covers only the 10 identity tables listed below. Use scripts/pg_backup.py
(full pg_dump, dedicated key, verified restore drill) - inspection finding F-26.

Automated Encrypted Database Backup Utility.
Performs:
1. Extraction of complete relational database records across all 10 core tables:
   - tenants, roles, permissions, role_permissions, organization_sites,
   - users, user_roles, session_revocations, audit_logs, feature_flags.
2. Derivation of 256-bit encryption key via PBKDF2-HMAC-SHA256.
3. AES-256-GCM authenticated encryption (confidentiality + integrity).
4. SHA-256 integrity checksum generation over ciphertext.
5. Strict omission of plain secrets, passwords, or PII in stdout/logs.
"""
import os
import sys
import json
import hashlib
import asyncio
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from sqlalchemy import select

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.backend.core.config import settings
from src.backend.core.database import AsyncSessionLocal
from src.backend.models.entities import (
    Tenant, OrganizationSite, User, Role, Permission,
    role_permissions, UserRole, SessionRevocation, AuditEvent, FeatureFlag
)

BACKUP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))

def derive_key(master_secret: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000
    )
    return kdf.derive(master_secret.encode("utf-8"))

async def export_data(session) -> dict:
    data = {
        "tenants": [],
        "roles": [],
        "permissions": [],
        "role_permissions": [],
        "organization_sites": [],
        "users": [],
        "user_roles": [],
        "session_revocations": [],
        "audit_logs": [],
        "feature_flags": []
    }
    
    # 1. Tenants
    t_res = await session.execute(select(Tenant))
    for t in t_res.scalars().all():
        data["tenants"].append({
            "id": t.id, "name": t.name, "slug": t.slug, "tier": t.tier, "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None
        })

    # 2. Roles
    r_res = await session.execute(select(Role))
    for r in r_res.scalars().all():
        data["roles"].append({
            "id": r.id, "name": r.name, "description": r.description, "is_privileged": r.is_privileged
        })

    # 3. Permissions
    p_res = await session.execute(select(Permission))
    for p in p_res.scalars().all():
        data["permissions"].append({
            "id": p.id, "code": p.code, "description": p.description, "domain": p.domain
        })

    # 4. Role Permissions (join table)
    rp_res = await session.execute(select(role_permissions))
    for row in rp_res.all():
        data["role_permissions"].append({
            "role_id": row.role_id, "permission_id": row.permission_id
        })

    # 5. Organization Sites
    s_res = await session.execute(select(OrganizationSite))
    for s in s_res.scalars().all():
        data["organization_sites"].append({
            "id": s.id, "tenant_id": s.tenant_id, "name": s.name, "code": s.code,
            "timezone": s.timezone, "currency": s.currency, "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if s.created_at else None
        })

    # 6. Users
    u_res = await session.execute(select(User))
    for u in u_res.scalars().all():
        data["users"].append({
            "id": u.id, "tenant_id": u.tenant_id, "email": u.email,
            "hashed_password": u.hashed_password, "full_name": u.full_name,
            "is_active": u.is_active, "is_verified": u.is_verified, "mfa_enabled": u.mfa_enabled,
            "mfa_secret": u.mfa_secret, "failed_login_attempts": u.failed_login_attempts,
            "locked_until": u.locked_until.isoformat() if u.locked_until else None,
            "created_at": u.created_at.isoformat() if u.created_at else None
        })

    # 7. User Roles
    ur_res = await session.execute(select(UserRole))
    for ur in ur_res.scalars().all():
        data["user_roles"].append({
            "user_id": ur.user_id, "role_id": ur.role_id, "tenant_id": ur.tenant_id
        })

    # 8. Session Revocations
    sr_res = await session.execute(select(SessionRevocation))
    for sr in sr_res.scalars().all():
        data["session_revocations"].append({
            "id": sr.id, "token_jti": sr.token_jti, "tenant_id": sr.tenant_id,
            "user_id": sr.user_id, "reason": sr.reason,
            "revoked_at": sr.revoked_at.isoformat() if sr.revoked_at else None,
            "expires_at": sr.expires_at.isoformat() if sr.expires_at else None
        })

    # 9. Audit Logs
    a_res = await session.execute(select(AuditEvent))
    for a in a_res.scalars().all():
        data["audit_logs"].append({
            "id": a.id, "tenant_id": a.tenant_id, "actor_id": a.actor_id, "event_type": a.event_type,
            "resource_type": a.resource_type, "resource_id": a.resource_id, "action": a.action,
            "ip_address": a.ip_address, "status": a.status,
            "timestamp": a.timestamp.isoformat() if a.timestamp else None
        })

    # 10. Feature Flags
    f_res = await session.execute(select(FeatureFlag))
    for f in f_res.scalars().all():
        data["feature_flags"].append({
            "id": f.id, "tenant_id": f.tenant_id, "key": f.key, "is_enabled": f.is_enabled,
            "rules_json": f.rules_json
        })

    return data

async def run_backup(
    destination_dir: str = BACKUP_DIR,
    secret_key: str = None,
    db_session=None
) -> dict:
    os.makedirs(destination_dir, exist_ok=True)
    master_key = secret_key or settings.jwt_secret_key
    
    if db_session:
        data = await export_data(db_session)
    else:
        async with AsyncSessionLocal() as session:
            data = await export_data(session)

    raw_json = json.dumps(data, indent=2).encode("utf-8")
    
    # Generate salt and nonce
    salt = os.urandom(16)
    nonce = os.urandom(12)
    derived_key = derive_key(master_key, salt)
    
    # AES-GCM Encrypt
    aesgcm = AESGCM(derived_key)
    encrypted_bytes = aesgcm.encrypt(nonce, raw_json, None)
    
    # Compute SHA-256 checksum over encrypted payload
    sha256_checksum = hashlib.sha256(encrypted_bytes).hexdigest()
    
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    enc_filename = f"backup_{timestamp_str}.enc"
    meta_filename = f"backup_{timestamp_str}.meta.json"
    
    enc_filepath = os.path.join(destination_dir, enc_filename)
    meta_filepath = os.path.join(destination_dir, meta_filename)
    
    with open(enc_filepath, "wb") as f:
        f.write(encrypted_bytes)
        
    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2HMAC-SHA256",
        "iterations": 100000,
        "salt_hex": salt.hex(),
        "nonce_hex": nonce.hex(),
        "sha256_checksum": sha256_checksum,
        "backup_file": enc_filename,
        "tables_included": list(data.keys()),
        "records_count": {k: len(v) for k, v in data.items()}
    }
    
    with open(meta_filepath, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return {
        "status": "SUCCESS",
        "encrypted_file": enc_filepath,
        "metadata_file": meta_filepath,
        "sha256_checksum": sha256_checksum,
        "counts": metadata["records_count"]
    }

if __name__ == "__main__":
    result = asyncio.run(run_backup())
    print(f"Encrypted backup generated successfully:")
    print(f"  File: {result['encrypted_file']}")
    print(f"  Checksum: {result['sha256_checksum']}")
    print(f"  Record counts: {result['counts']}")
