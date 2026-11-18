"""
Step 02 Security Test Suite: Encrypted Backup & Recovery Substrate.
Controls: 54, 55, 56 (Data backup, encryption at rest, recovery validation).
"""
import pytest
import os
import json
import tempfile
import asyncio
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.backend.models.entities import Base, Tenant, User, Role
from src.backend.core.security import SecurityService
from scripts.backup_database import run_backup
from scripts.restore_database import restore_from_backup, ChecksumMismatchError, DecryptionError

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_test_backup_db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t1 = Tenant(id="tenant_backup_1", name="Backup Test Corp", slug="backup-corp", is_active=True)
        session.add(t1)
        await session.flush()

        u1 = User(
            id="user_backup_1",
            tenant_id="tenant_backup_1",
            email="backup_admin@corp.com",
            hashed_password=SecurityService.hash_password("AdminPass123!"),
            full_name="Backup Admin",
            is_active=True,
            is_verified=True
        )
        session.add(u1)
        await session.commit()

    try:
        yield engine, session_factory
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_backup_and_restore_cycle_integrity():
    """
    Control 54, 55, 56:
    Creates an encrypted backup, validates checksum and AES-GCM encryption,
    and restores the database into a clean schema, verifying 100% record fidelity.
    """
    async with get_test_backup_db() as (engine, session_factory):
        test_key = "a_very_strong_master_encryption_key_32chars!"

        with tempfile.TemporaryDirectory() as tmp_dir:
            # 1. Execute Backup
            async with session_factory() as s_orig:
                backup_result = await run_backup(
                    destination_dir=tmp_dir,
                    secret_key=test_key,
                    db_session=s_orig
                )

            assert backup_result["status"] == "SUCCESS"
            assert os.path.exists(backup_result["encrypted_file"])
            assert os.path.exists(backup_result["metadata_file"])

            # Check metadata
            with open(backup_result["metadata_file"], "r", encoding="utf-8") as f:
                meta = json.load(f)
            assert meta["algorithm"] == "AES-256-GCM"
            assert meta["sha256_checksum"] == backup_result["sha256_checksum"]
            assert meta["records_count"]["tenants"] >= 1
            assert meta["records_count"]["users"] >= 1

            # Confirm file is truly encrypted (not raw JSON)
            with open(backup_result["encrypted_file"], "rb") as f:
                raw_bytes = f.read()
            with pytest.raises(Exception):
                raw_bytes.decode("utf-8") # Must not be valid utf-8 json string

            # 2. Restore into a brand new clean database
            restore_engine = create_async_engine(TEST_DB_URL, echo=False)
            restore_factory = async_sessionmaker(bind=restore_engine, class_=AsyncSession, expire_on_commit=False)
            async with restore_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with restore_factory() as s_target:
                restore_res = await restore_from_backup(
                    metadata_path=backup_result["metadata_file"],
                    secret_key=test_key,
                    session_override=s_target
                )

                assert restore_res["status"] == "RESTORED"
                assert restore_res["verified_checksum"] == backup_result["sha256_checksum"]

                # 3. Assert restored data exists in target DB
                t_restored = (await s_target.execute(select(Tenant).where(Tenant.id == "tenant_backup_1"))).scalars().first()
                assert t_restored is not None
                assert t_restored.name == "Backup Test Corp"

                u_restored = (await s_target.execute(select(User).where(User.id == "user_backup_1"))).scalars().first()
                assert u_restored is not None
                assert u_restored.email == "backup_admin@corp.com"

            await restore_engine.dispose()

@pytest.mark.asyncio
async def test_restore_fails_on_tampered_checksum():
    """Control 56: Verifies that tampered or corrupted backup ciphertext is detected and rejected."""
    async with get_test_backup_db() as (engine, session_factory):
        test_key = "a_very_strong_master_encryption_key_32chars!"

        with tempfile.TemporaryDirectory() as tmp_dir:
            async with session_factory() as s_orig:
                backup_result = await run_backup(
                    destination_dir=tmp_dir,
                    secret_key=test_key,
                    db_session=s_orig
                )

            # Corrupt 1 byte in the encrypted file
            enc_file = backup_result["encrypted_file"]
            with open(enc_file, "r+b") as f:
                data = bytearray(f.read())
                data[10] ^= 0xFF
                f.seek(0)
                f.write(data)

            # Attempt restore -> must fail with ChecksumMismatchError
            with pytest.raises(ChecksumMismatchError):
                await restore_from_backup(
                    metadata_path=backup_result["metadata_file"],
                    secret_key=test_key
                )

@pytest.mark.asyncio
async def test_restore_fails_on_incorrect_key():
    """Control 55: Attempting restore with an invalid master secret triggers DecryptionError."""
    async with get_test_backup_db() as (engine, session_factory):
        correct_key = "correct_master_encryption_key_32chars!"
        wrong_key = "wrong_incorrect_master_key_32chars!"

        with tempfile.TemporaryDirectory() as tmp_dir:
            async with session_factory() as s_orig:
                backup_result = await run_backup(
                    destination_dir=tmp_dir,
                    secret_key=correct_key,
                    db_session=s_orig
                )

            with pytest.raises(DecryptionError):
                await restore_from_backup(
                    metadata_path=backup_result["metadata_file"],
                    secret_key=wrong_key
                )
