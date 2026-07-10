"""OpenAI multilingual embeddings + Mongo-backed cache.

Uses `text-embedding-3-small` — multilingual, cheap ($0.02 per 1M tokens,
so ~$0.000001 per typical question). Every unique normalized prompt is
embedded exactly once; subsequent calls hit the Mongo cache.
"""
from __future__ import annotations

import math
import os
import time
from typing import Optional, Sequence

from openai import AsyncOpenAI

from .language import normalize_prompt

EMBED_MODEL = "text-embedding-3-small"  # multilingual, 1536-dim
EMBED_PRICE_PER_M_TOK = 0.02  # USD


class Embedder:
    def __init__(self) -> None:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.available = bool(key)
        self._client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=key) if key else None

    async def embed(self, text: str) -> tuple[Optional[Sequence[float]], int, float]:
        """Return (vector or None, tokens_used, cost_usd). None vector means unavailable."""
        if not self._client:
            return None, 0, 0.0
        resp = await self._client.embeddings.create(model=EMBED_MODEL, input=text)
        vec = resp.data[0].embedding
        tokens = getattr(resp.usage, "total_tokens", 0) or 0
        cost = round((tokens / 1_000_000) * EMBED_PRICE_PER_M_TOK, 8)
        return vec, tokens, cost


async def get_or_create_embedding(db, prompt: str) -> tuple[Optional[Sequence[float]], dict]:
    """Return the cached embedding for `prompt` or create a new one.

    Returns (vector, meta) where meta contains: cache_hit, tokens, cost_usd, model.
    Vector will be None if the embedder isn't available (no OPENAI_API_KEY).
    """
    norm = normalize_prompt(prompt)
    cached = await db.embeddings.find_one({"norm": norm}, {"_id": 0})
    if cached:
        return cached["vector"], {
            "cache_hit": True, "tokens": 0, "cost_usd": 0.0, "model": cached.get("model", EMBED_MODEL),
        }
    embedder = Embedder()
    vec, tokens, cost = await embedder.embed(prompt)
    if vec is None:
        return None, {"cache_hit": False, "tokens": 0, "cost_usd": 0.0, "model": None}
    await db.embeddings.insert_one({
        "norm": norm,
        "prompt": prompt,
        "vector": list(vec),
        "model": EMBED_MODEL,
        "tokens": tokens,
        "cost_usd": cost,
        "created_at": time.time(),
    })
    return vec, {"cache_hit": False, "tokens": tokens, "cost_usd": cost, "model": EMBED_MODEL}


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
