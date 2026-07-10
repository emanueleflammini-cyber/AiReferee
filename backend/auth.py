"""User + identity model for AI Referee.

The identity layer is intentionally minimal: it accepts a stable user ID
from an `X-User-Id` header and looks up (or creates) the corresponding
row in the `users` collection. When real authentication ships later
(JWT, session cookie, OAuth), only `get_identity()` needs to be swapped
— every route that already depends on it will continue to work.

Anonymous requests (no header) resolve to `IdentityContext(user_id=None,
plan=FREE, is_anonymous=True)` so the public MVP flow (contest demo) is
unaffected. Rate limits and BYOK are only applied to identified users.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException, Request

from providers.plans import Plan, Entitlements, entitlements_for

log = logging.getLogger(__name__)

USER_ID_HEADER = "X-User-Id"
ADMIN_TOKEN_HEADER = "X-Admin-Token"


@dataclass(frozen=True)
class IdentityContext:
    user_id: Optional[str]
    plan: Plan
    entitlements: Entitlements
    is_anonymous: bool

    @property
    def plan_value(self) -> str:
        return self.plan.value


# --------------------------------------------------------------------------
# FastAPI dependency
# --------------------------------------------------------------------------

async def get_identity(request: Request) -> IdentityContext:
    """Resolve the caller's identity + plan.

    * No `X-User-Id` header  -> anonymous, FREE plan.
    * With header            -> upsert into `users`, return their stored plan.

    The upsert is idempotent and cheap — one indexed lookup + optional
    insert. This lets the frontend call any protected endpoint with a
    stable UUID and get a persistent plan without going through billing.
    """
    user_id = request.headers.get(USER_ID_HEADER, "").strip()
    if not user_id:
        ents = entitlements_for(Plan.FREE)
        return IdentityContext(user_id=None, plan=Plan.FREE, entitlements=ents, is_anonymous=True)

    from server import db  # local import — avoid circular at module load.
    users = db["users"]
    now_iso = datetime.now(timezone.utc).isoformat()
    doc = await users.find_one({"id": user_id}, {"_id": 0})
    if not doc:
        doc = {
            "id": user_id,
            "plan": Plan.FREE.value,
            "created_at": now_iso,
            "last_seen_at": now_iso,
        }
        await users.insert_one(doc)
    else:
        await users.update_one({"id": user_id}, {"$set": {"last_seen_at": now_iso}})

    try:
        plan = Plan(doc.get("plan", Plan.FREE.value))
    except ValueError:
        plan = Plan.FREE
    ents = entitlements_for(plan)
    return IdentityContext(user_id=user_id, plan=plan, entitlements=ents, is_anonymous=False)


async def require_admin(x_admin_token: str = Header(default="", alias=ADMIN_TOKEN_HEADER)) -> None:
    """Guard admin-only endpoints.

    Uses a shared secret from `ADMIN_TOKEN` env. If the env var is unset
    the guard fails closed — refusing all requests — so a missing secret
    can never accidentally expose the admin surface.
    """
    expected = os.environ.get("ADMIN_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Admin surface is disabled — set ADMIN_TOKEN in backend/.env")
    if not x_admin_token or x_admin_token.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token")


# --------------------------------------------------------------------------
# Rate limiting (per-user, per-day)
# --------------------------------------------------------------------------

def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def enforce_daily_compare_limit(identity: IdentityContext) -> int:
    """Increment today's compare counter for the user and return the new value.

    Anonymous requests are NOT rate-limited (returns 0). This keeps the
    public demo smooth and mirrors the "signed-in only" gating we plan
    to enforce once real auth is added.

    Raises HTTP 429 when the identified user exceeds their daily limit.
    """
    if identity.is_anonymous or identity.user_id is None:
        return 0

    from pymongo import ReturnDocument  # local import — pymongo is already a Motor dep.
    from server import db  # local import avoids circular.
    events = db["usage_events"]
    key = {"user_id": identity.user_id, "day": _today_key(), "kind": "compare"}
    doc = await events.find_one_and_update(
        key,
        {"$inc": {"count": 1}, "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    count = int((doc or {}).get("count", 1))

    limit = identity.entitlements.daily_compare_limit
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily compare limit reached for plan '{identity.plan.value}' ({count - 1}/{limit}). Try again tomorrow or upgrade.",
        )
    return count
