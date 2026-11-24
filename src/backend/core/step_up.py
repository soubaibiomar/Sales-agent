"""
Server-side step-up MFA verification (inspection findings F-03, F-04, F-06).

Security state must never be asserted by the client: no `X-MFA-Verified` header,
no `?mfa_verified=true` query flag, no "any non-empty code" and no length-only checks.
A step-up is satisfied only by
  * an access token minted after a successful TOTP verification (`mfa_verified` claim,
    signed by the server), when the operation allows session-level MFA, or
  * a TOTP code verified against the caller's enrolled, encrypted seed.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.security import SecurityService
from src.backend.models.entities import User


async def verify_user_totp(db: AsyncSession, tenant_id: str, user_id: str, code: Optional[str]) -> bool:
    """Verifies a TOTP code against the user's enrolled seed. Fails closed."""
    if not code or not code.strip().isdigit():
        return False
    user = (await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )).scalars().first()
    if not user or not user.is_active or not user.mfa_enabled or not user.mfa_secret:
        return False
    try:
        return SecurityService.verify_totp(user.mfa_secret, code.strip())
    except Exception:  # noqa: BLE001 - undecryptable/malformed seed => reject
        return False


async def is_step_up_satisfied(db: AsyncSession, ctx, code: Optional[str], allow_session_mfa: bool = True) -> bool:
    """
    True when the caller proved a second factor.
    allow_session_mfa=False forces a fresh TOTP (used for spoken high-risk commands).
    """
    if allow_session_mfa and getattr(ctx, "mfa_verified", False):
        return True
    return await verify_user_totp(db, ctx.tenant_id, ctx.user_id, code)
