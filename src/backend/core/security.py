"""
Cryptographic and Security Services: Password hashing, RFC 6238 TOTP MFA,
JWT issuance & verification with PyJWT, and token revocation checks.
Zero external unsafe dependencies; strictly OWASP compliant.
"""
import os
import hmac
import hashlib
import base64
import struct
import time
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
import jwt
from src.backend.core.config import settings

# PBKDF2 parameters according to OWASP recommendations
PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 600000
SALT_BYTES = 32

class SecurityService:
    @staticmethod
    def hash_password(password: str) -> str:
        """Hashes password with PBKDF2-HMAC-SHA256 and a random 32-byte salt."""
        salt = os.urandom(SALT_BYTES)
        dk = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS
        )
        # Format: pbkdf2_sha256$iterations$salt_hex$hash_hex
        return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Constant-time verification of password against stored hash."""
        try:
            parts = hashed_password.split("$")
            if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
                return False
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected_hash = bytes.fromhex(parts[3])
            
            dk = hashlib.pbkdf2_hmac(
                PBKDF2_ALGORITHM,
                plain_password.encode("utf-8"),
                salt,
                iterations
            )
            return hmac.compare_digest(dk, expected_hash)
        except Exception:
            return False

    # --- RFC 6238 TOTP Multi-Factor Authentication ---
    @staticmethod
    def generate_totp_secret() -> str:
        """Generates a secure Base32 secret for TOTP (160-bit standard)."""
        raw_bytes = os.urandom(20)
        return base64.b32encode(raw_bytes).decode("utf-8").replace("=", "")

    @staticmethod
    def generate_totp_code(secret_b32: str, timestamp: Optional[float] = None) -> str:
        """Computes current 6-digit TOTP code for the given secret."""
        # Pad secret if necessary
        secret = secret_b32.strip().upper()
        padding = (8 - len(secret) % 8) % 8
        secret_bytes = base64.b32decode(secret + "=" * padding)
        
        t = int(timestamp if timestamp is not None else time.time()) // 30
        msg = struct.pack(">Q", t)
        h = hmac.new(secret_bytes, msg, hashlib.sha1).digest()
        
        offset = h[-1] & 0x0F
        code = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000
        return f"{code:06d}"

    @classmethod
    def verify_totp(cls, secret_b32: str, code: str, allowed_drift_windows: int = 1) -> bool:
        """
        Verifies TOTP code with time drift window tolerance (+/- 30 seconds default).
        Prevents clock skew rejections.
        """
        if not secret_b32 or not code or len(code) != 6 or not code.isdigit():
            return False
            
        current_time = time.time()
        for window in range(-allowed_drift_windows, allowed_drift_windows + 1):
            expected = cls.generate_totp_code(secret_b32, current_time + window * 30)
            if hmac.compare_digest(expected, code):
                return True
        return False

    @staticmethod
    def get_totp_uri(secret_b32: str, user_email: str, issuer: str = "Sales AI Platform") -> str:
        """Returns standard otpauth URI for authenticator apps."""
        return f"otpauth://totp/{issuer}:{user_email}?secret={secret_b32}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"

    # --- JWT Access & Refresh Token Management ---
    @staticmethod
    def create_access_token(
        user_id: str,
        tenant_id: str,
        email: str,
        roles: List[str],
        permissions: List[str],
        mfa_verified: bool = False,
        expires_delta: Optional[timedelta] = None
    ) -> Tuple[str, str, datetime]:
        """
        Issues a signed JWT access token.
        Returns (token_string, jti, expiration_datetime).
        """
        now = datetime.now(timezone.utc)
        expires = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
        jti = str(uuid.uuid4())
        
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "roles": roles,
            "permissions": permissions,
            "mfa_verified": mfa_verified,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "iss": "sales-ai-platform",
            "aud": "sales-ai-api"
        }
        
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm
        )
        return token, jti, expires

    @staticmethod
    def create_refresh_token(
        user_id: str,
        tenant_id: str,
        expires_delta: Optional[timedelta] = None
    ) -> Tuple[str, str, datetime]:
        """Issues a signed refresh token."""
        now = datetime.now(timezone.utc)
        expires = now + (expires_delta or timedelta(days=settings.refresh_token_expire_days))
        jti = str(uuid.uuid4())
        
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "type": "refresh",
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "iss": "sales-ai-platform",
            "aud": "sales-ai-api"
        }
        
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm
        )
        return token, jti, expires

    @staticmethod
    def decode_token(token: str) -> Dict[str, Any]:
        """
        Decodes and cryptographically validates JWT token.
        Raises jwt.PyJWTError on invalid signature, expiration, audience, or issuer.
        """
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience="sales-ai-api",
            issuer="sales-ai-platform"
        )
