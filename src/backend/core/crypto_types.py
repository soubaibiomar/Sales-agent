"""
At-rest encryption for credential columns (inspection finding F-30).

`EncryptedSecret` is a SQLAlchemy column type that stores AES-256-GCM ciphertext
(`enc:v1:<nonce_hex>:<ciphertext_hex>`) and returns plaintext to the application.
Rows written before encryption was introduced (no prefix) are still readable and are
re-encrypted the next time they are saved (see migrations/encrypt_channel_secrets.py).
The key comes from INTEGRATION_SECRET_KEY, which the startup guard refuses to leave at
its development default outside development.
"""
import hashlib
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator

PREFIX = "enc:v1:"


def _key() -> bytes:
    from src.backend.core.config import settings
    return hashlib.sha256(settings.integration_secret_key.encode("utf-8")).digest()


def encrypt_secret(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None or plaintext == "" or plaintext.startswith(PREFIX):
        return plaintext
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode("utf-8"), b"integration-secret")
    return f"{PREFIX}{nonce.hex()}:{ct.hex()}"


def decrypt_secret(stored: Optional[str]) -> Optional[str]:
    if not stored or not stored.startswith(PREFIX):
        return stored  # legacy plaintext row
    nonce_hex, ct_hex = stored[len(PREFIX):].split(":", 1)
    return AESGCM(_key()).decrypt(bytes.fromhex(nonce_hex), bytes.fromhex(ct_hex), b"integration-secret").decode("utf-8")


class EncryptedSecret(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):
        return decrypt_secret(value)
