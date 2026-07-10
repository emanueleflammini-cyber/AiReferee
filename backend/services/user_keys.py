"""Encrypted user-owned API key storage for the future BYOK plan.

Design guarantees:
    * Keys are encrypted at rest using Fernet (symmetric AES-128).
    * The Fernet key comes from `USER_KEY_ENCRYPTION_KEY` in the environment.
      If it isn't set, encryption is REFUSED (we never store keys in plaintext).
    * Decrypted keys never leave this module except through the two return
      values below. Callers must never log them.
    * All logs redact the key. Only the tail (last 4 chars) may be emitted.

The MongoDB collection is `user_provider_keys` with schema:
    { user_id, provider_id, ciphertext, hint (last 4 chars), created_at }

This module exposes just three functions (get / set / delete) — enough for
the future BYOK UI to plug in without touching the compare engine.

Nothing in this module is wired into a HTTP route yet — the intent is to
prepare the abstraction, per the current milestone.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


def _fernet():
    """Return a Fernet instance if a valid key is configured, else None.

    We keep this lazy so importing the module never crashes when the key
    isn't set (development environments, tests, etc.).
    """
    raw = os.environ.get("USER_KEY_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(raw.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Fernet init failed — refusing to touch user keys (%s)", exc)
        return None


def _hint(k: str) -> str:
    return k[-4:] if len(k) >= 4 else "****"


# --------------------------------------------------------------------------
# Public API. All Mongo access is done via `server.db` to reuse the app's
# single Motor client. Imports are lazy to avoid a circular dependency
# between server.py and this module.
# --------------------------------------------------------------------------


def _collection():
    from server import db  # local import — server.py owns the Motor client.
    return db["user_provider_keys"]


async def set_user_key(user_id: str, provider_id: str, api_key: str) -> bool:
    """Store an encrypted user key. Returns True on success.

    Refuses to store anything when Fernet isn't configured — this is
    intentional: we never store user keys in plaintext.
    """
    fernet = _fernet()
    if fernet is None:
        log.warning("set_user_key refused — USER_KEY_ENCRYPTION_KEY is not configured.")
        return False
    if not api_key or not api_key.strip():
        return False
    ciphertext = fernet.encrypt(api_key.strip().encode("utf-8")).decode("utf-8")
    doc = {
        "user_id": user_id,
        "provider_id": provider_id,
        "ciphertext": ciphertext,
        "hint": _hint(api_key.strip()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await _collection().update_one(
        {"user_id": user_id, "provider_id": provider_id},
        {"$set": doc, "$setOnInsert": {"created_at": doc["updated_at"]}},
        upsert=True,
    )
    log.info("Stored user key for user=%s provider=%s hint=****%s", user_id, provider_id, _hint(api_key))
    return True


async def delete_user_key(user_id: str, provider_id: str) -> int:
    res = await _collection().delete_one({"user_id": user_id, "provider_id": provider_id})
    return res.deleted_count


# --------------------------------------------------------------------------
# Synchronous read helpers — used by providers/key_source.resolve_api_key.
# We use PyMongo's synchronous client for these because the provider
# constructor path is synchronous. Motor and PyMongo can safely share a
# single MongoDB deployment; the tiny cost is worth avoiding an event-loop
# hop in the hot path.
# --------------------------------------------------------------------------

_sync_client = None


def _sync_collection():
    global _sync_client
    if _sync_client is None:
        try:
            from pymongo import MongoClient
            _sync_client = MongoClient(os.environ["MONGO_URL"])
        except Exception as exc:  # noqa: BLE001
            log.debug("Sync Mongo client init failed: %s", exc)
            return None
    db_name = os.environ.get("DB_NAME", "test_database")
    return _sync_client[db_name]["user_provider_keys"]


def get_decrypted_user_key(user_id: str, provider_id: str) -> Optional[str]:
    """Return the decrypted user key or None. Never logs the plaintext."""
    fernet = _fernet()
    if fernet is None:
        return None
    coll = _sync_collection()
    if coll is None:
        return None
    doc = coll.find_one({"user_id": user_id, "provider_id": provider_id})
    if not doc or "ciphertext" not in doc:
        return None
    try:
        return fernet.decrypt(doc["ciphertext"].encode("utf-8")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to decrypt user key user=%s provider=%s (%s)", user_id, provider_id, exc)
        return None
