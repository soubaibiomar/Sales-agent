"""
One-off data migration for 016 (F-30): re-saves every plaintext integration secret so the
EncryptedSecret column type stores it as AES-256-GCM ciphertext. Idempotent; prints only
counts (never secrets). Run with a DATABASE_URL allowed to update tenant_channel_integrations.
"""
import asyncio

from sqlalchemy import select, text

from src.backend.core.crypto_types import PREFIX, encrypt_secret
from src.backend.core.database import engine


async def main() -> None:
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT id, webhook_secret FROM tenant_channel_integrations WHERE webhook_secret IS NOT NULL"
        ))).all()
        pending = [(rid, val) for rid, val in rows if val and not val.startswith(PREFIX)]
        for rid, val in pending:
            await conn.execute(text("UPDATE tenant_channel_integrations SET webhook_secret = :v WHERE id = :i"),
                               {"v": encrypt_secret(val), "i": rid})
    print({"rows_with_secret": len(rows), "re_encrypted": len(pending)})


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
