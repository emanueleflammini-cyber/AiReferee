from fastapi import FastAPI, APIRouter, HTTPException, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import os
import re
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Any, Dict
import uuid
from datetime import datetime, timezone


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from providers import selected_providers, provider_status, all_provider_specs, fallback_for  # noqa: E402
from providers.plans import PLAN_ENTITLEMENTS, Plan  # noqa: E402
from providers.embeddings import get_or_create_embedding, cosine, EMBED_MODEL  # noqa: E402
from providers.language import detect_language, normalize_prompt as lang_normalize, SUPPORTED as SUPPORTED_LANGS  # noqa: E402
from providers.translator import Translator, LANG_NAMES  # noqa: E402
from auth import IdentityContext, get_identity, require_admin, enforce_daily_compare_limit  # noqa: E402

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="AI Referee API")
api_router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------
# Smart Reuse — topic classification, normalization, similarity
# --------------------------------------------------------------------------

NEVER_REUSE_KEYWORDS = {
    "today", "now", "tonight", "latest", "current", "currently", "yesterday",
    "price", "prices", "cost", "weather", "stock", "stocks", "news",
    "trending", "score", "scores", "match", "election", "results",
}
ALWAYS_REFRESH_KEYWORDS = {
    "medical", "medicine", "doctor", "diagnose", "diagnosis", "symptom",
    "symptoms", "prescription", "dose", "dosage",
    "legal", "law", "lawyer", "lawsuit", "attorney", "court", "sue",
    "tax", "taxes", "invest", "investing", "investment", "financial",
    "finance", "insurance", "loan", "mortgage",
    "cancer", "disease", "illness", "treatment",
}
TECHNICAL_KEYWORDS = {
    "code", "programming", "database", "databases", "algorithm", "algorithms",
    "api", "framework", "python", "javascript", "typescript", "react",
    "node", "docker", "kubernetes", "sql", "http", "https", "compiler",
    "distributed", "async", "concurrency", "protocol", "encryption",
    "microservice", "microservices", "cache", "caching", "queue", "kafka",
}

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "for", "to", "and", "or", "with", "that", "this",
    "it", "as", "at", "by", "from", "into", "about", "than", "then",
    "how", "why", "what", "when", "where", "who", "which", "whose",
    "do", "does", "did", "can", "could", "would", "should", "will",
    "i", "you", "we", "they", "he", "she", "them", "my", "your", "our",
    "some", "any", "all", "no", "not", "so", "if", "but",
}

CACHE_TTL_DAYS = {
    "news": 0,
    "sensitive": 0,
    "technical": 14,
    "stable": 30,
    "moderate": 7,
    "personal": 0,
}

# Configurable semantic thresholds — tune via env if needed.
SIM_NEAR_EXACT   = float(os.environ.get("REUSE_SIM_NEAR_EXACT", "0.95"))
SIM_STRONG_MATCH = float(os.environ.get("REUSE_SIM_STRONG",     "0.88"))
# Fallback Jaccard threshold used when no embeddings are available.
# Kept as a single knob (SMART_REUSE_THRESHOLD) so pricing/tuning can be adjusted
# without touching the comparison engine.
SIM_THRESHOLD = float(os.environ.get("SMART_REUSE_THRESHOLD", "0.55"))

# Assumed savings per avoided comparison (approximate real cost of 4 model calls today).
ASSUMED_SAVED_COST_USD = float(os.environ.get("REUSE_SAVED_COST", "0.00030"))
ASSUMED_SAVED_LATENCY_MS = int(os.environ.get("REUSE_SAVED_LATENCY_MS", "8000"))
ASSUMED_SAVED_TOKENS_PER_CALL = 200


def normalize_prompt(p: str) -> str:  # kept for backward-compat
    return lang_normalize(p)


def tokens_of(p: str):
    return set(normalize_prompt(p).split()) - STOP_WORDS


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def classify_topic(p: str) -> str:
    toks = tokens_of(p)
    if toks & NEVER_REUSE_KEYWORDS:
        return "news"
    if toks & ALWAYS_REFRESH_KEYWORDS:
        return "sensitive"
    if toks & TECHNICAL_KEYWORDS:
        return "technical"
    return "stable"


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


class QueryCreate(BaseModel):
    prompt: str
    goal: int = 50
    detail: int = 50
    audience: str = "professional"
    format: str = "paragraph"
    strategy: str = "balanced"


class QueryRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str
    goal: int
    detail: int
    audience: str
    format: str
    strategy: str = "balanced"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MatchRequest(BaseModel):
    prompt: str
    answer_language: Optional[str] = None
    auto_detect_language: bool = True


class MatchResponse(BaseModel):
    policy: str          # reusable | never_reuse | always_refresh
    topic: str           # stable | technical | sensitive | news
    question_language: str = "en"
    match: Optional[Dict[str, Any]] = None
    reason: str
    ttl_days: int
    thresholds: Dict[str, float] = {}
    savings: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@api_router.get("/")
async def root():
    return {"message": "AI Referee API is running", "version": "0.2.0"}


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_obj = StatusCheck(**input.model_dump())
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for check in status_checks:
        if isinstance(check.get('timestamp'), str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    return status_checks


@api_router.post("/queries", response_model=QueryRecord)
async def create_query(payload: QueryCreate):
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")

    record = QueryRecord(**payload.model_dump())
    doc = record.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    await db.queries.insert_one(doc)

    topic = classify_topic(payload.prompt)
    if topic in ("technical", "stable"):
        # Detect the language locally (no API cost).
        lang = detect_language(payload.prompt)
        # Generate (or reuse) a multilingual embedding — very cheap.
        vec, embed_meta = await get_or_create_embedding(db, payload.prompt)

        await db.conclusions.insert_one({
            "id": record.id,
            "prompt": payload.prompt,
            "prompt_norm": normalize_prompt(payload.prompt),
            "prompt_tokens": list(tokens_of(payload.prompt)),
            "topic": topic,
            "language": lang,
            "trust_score": 92,
            "consensus": 87,
            "confidence": 82,
            "is_public": True,
            "is_time_sensitive": topic == "news",
            "category": "stable" if topic == "stable" else "technical",
            "embedding": list(vec) if vec is not None else None,
            "embedding_model": embed_meta.get("model"),
            "created_at": doc['created_at'],
        })
    return record


@api_router.get("/queries", response_model=List[QueryRecord])
async def list_queries(limit: int = 50):
    limit = max(1, min(limit, 200))
    items = await db.queries.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    for it in items:
        if isinstance(it.get('created_at'), str):
            it['created_at'] = datetime.fromisoformat(it['created_at'])
    return items


@api_router.get("/queries/{query_id}", response_model=QueryRecord)
async def get_query(query_id: str):
    doc = await db.queries.find_one({"id": query_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Query not found")
    if isinstance(doc.get('created_at'), str):
        doc['created_at'] = datetime.fromisoformat(doc['created_at'])
    return doc


@api_router.post("/queries/match", response_model=MatchResponse)
async def match_query(req: MatchRequest):
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    topic = classify_topic(prompt)
    ttl = CACHE_TTL_DAYS.get(topic, 0)
    q_lang = detect_language(prompt) if req.auto_detect_language else "en"
    target_lang = (req.answer_language or q_lang or "en").lower()
    thresholds = {
        "near_exact": SIM_NEAR_EXACT,
        "strong": SIM_STRONG_MATCH,
        "jaccard_fallback": SIM_THRESHOLD,
    }

    if topic == "news":
        return MatchResponse(
            policy="never_reuse", topic=topic, question_language=q_lang,
            reason="News, prices, weather and current-event topics are never cached — this will be fetched fresh.",
            ttl_days=0, thresholds=thresholds,
        )
    if topic == "sensitive":
        return MatchResponse(
            policy="always_refresh", topic=topic, question_language=q_lang,
            reason="Financial, legal and medical topics always run a fresh comparison for safety.",
            ttl_days=0, thresholds=thresholds,
        )

    # ---- Semantic matching via multilingual embeddings (with Jaccard fallback) ----
    now = datetime.now(timezone.utc)
    query_vec, _ = await get_or_create_embedding(db, prompt)
    best_doc = None
    best_score = 0.0
    best_method = "jaccard"

    if query_vec is not None:
        # Linear scan against recent public conclusions with an embedding.
        cursor = db.conclusions.find(
            {"embedding": {"$ne": None}, "is_public": True},
            {"_id": 0},
        ).sort("created_at", -1).limit(300)
        async for doc in cursor:
            score = cosine(query_vec, doc.get("embedding") or [])
            if score > best_score:
                best_score = score
                best_doc = doc
                best_method = "embedding"

    # Fallback to Jaccard on tokens if embeddings unavailable or scored low
    if best_score < SIM_STRONG_MATCH:
        toks = tokens_of(prompt)
        async for doc in db.conclusions.find({"is_public": True}, {"_id": 0}).sort("created_at", -1).limit(300):
            prev_toks = set(doc.get("prompt_tokens", []))
            score = jaccard(toks, prev_toks)
            if score > best_score and score >= SIM_THRESHOLD:
                best_score = score
                best_doc = doc
                best_method = "jaccard"

    # No match at all
    if best_doc is None or best_score < min(SIM_STRONG_MATCH, SIM_THRESHOLD):
        return MatchResponse(
            policy="reusable", topic=topic, question_language=q_lang,
            reason="No similar prior conclusion in cache — this will be a fresh comparison.",
            ttl_days=ttl, thresholds=thresholds,
        )

    # TTL check
    created = best_doc.get("created_at")
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    age = now - created
    age_days = max(0, age.days)
    if age_days > ttl:
        return MatchResponse(
            policy="reusable", topic=topic, question_language=q_lang,
            reason=f"A prior conclusion exists but exceeds the {ttl}-day cache window for this topic.",
            ttl_days=ttl, thresholds=thresholds,
        )

    # Trust guardrail
    if best_doc.get("trust_score", 0) < 60:
        return MatchResponse(
            policy="reusable", topic=topic, question_language=q_lang,
            reason="A match exists but its trust score is below the reuse floor.",
            ttl_days=ttl, thresholds=thresholds,
        )

    stored_lang = best_doc.get("language", "en")
    tier = ("near_exact" if best_score >= SIM_NEAR_EXACT
            else "strong" if best_score >= SIM_STRONG_MATCH
            else "weak")
    needs_translation = (best_method == "embedding") and (stored_lang != target_lang)

    match = {
        "id": best_doc["id"],
        "prompt": best_doc["prompt"],
        "created_at": created.isoformat(),
        "age_days": age_days,
        "similarity": round(best_score * 100),
        "similarity_tier": tier,
        "match_method": best_method,
        "confidence": best_doc.get("confidence", 82),
        "consensus": best_doc.get("consensus", 87),
        "trust": best_doc.get("trust_score", 92),
        "topic": topic,
        "original_language": stored_lang,
        "answer_language": target_lang,
        "needs_translation": needs_translation,
    }
    live_count = len([p for p in all_provider_specs() if p.get("live")])
    api_calls_avoided = max(live_count, 1)
    savings = {
        "api_calls_avoided": api_calls_avoided,
        "tokens_avoided": api_calls_avoided * ASSUMED_SAVED_TOKENS_PER_CALL,
        "cost_saved_usd": round(ASSUMED_SAVED_COST_USD * (api_calls_avoided / 2), 6),
        "response_time_saved_ms": ASSUMED_SAVED_LATENCY_MS,
    }
    return MatchResponse(
        policy="reusable", topic=topic, question_language=q_lang, match=match,
        reason=f"{tier.replace('_', ' ')} match ({match['similarity']}%, {age_days}d old, via {best_method}).",
        ttl_days=ttl, thresholds=thresholds, savings=savings,
    )


# --------------------------------------------------------------------------
# /api/conclusions/{id}/translate — translate ONLY the final conclusion
# --------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    target_language: str


class TranslateResponse(BaseModel):
    conclusion_id: str
    source_language: str
    target_language: str
    text: str
    cache_hit: bool
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    model_used: str = ""


@api_router.post("/conclusions/{conclusion_id}/translate", response_model=TranslateResponse)
async def translate_conclusion(conclusion_id: str, req: TranslateRequest):
    target = (req.target_language or "en").lower()
    doc = await db.conclusions.find_one({"id": conclusion_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Conclusion not found")
    source_lang = doc.get("language", "en")
    source_version = doc.get("version", 1)

    # 1) Same-language: no translation needed.
    if source_lang == target:
        return TranslateResponse(
            conclusion_id=conclusion_id, source_language=source_lang, target_language=target,
            text=doc.get("trusted_conclusion") or doc.get("prompt", ""),
            cache_hit=True, input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0.0, model_used="none",
        )

    # 2) Translation cache lookup — key = (conclusion_id, target, source_version)
    cache_key = {"conclusion_id": conclusion_id, "target_language": target, "source_version": source_version}
    cached = await db.translation_cache.find_one(cache_key, {"_id": 0})
    if cached:
        return TranslateResponse(
            conclusion_id=conclusion_id, source_language=source_lang, target_language=target,
            text=cached["text"], cache_hit=True,
            input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0.0, model_used=cached.get("model_used", ""),
        )

    # 3) Real translation call — ONLY the final conclusion body.
    body = doc.get("trusted_conclusion") or doc.get("prompt", "")
    tr = Translator()
    if not tr.available:
        raise HTTPException(status_code=503, detail="No translator configured (OPENAI_API_KEY missing).")
    out = await tr.translate(body, target_lang=target, source_lang=source_lang)

    # 4) Save to cache
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.translation_cache.insert_one({
        **cache_key,
        "text": out["text"],
        "input_tokens": out["input_tokens"],
        "output_tokens": out["output_tokens"],
        "cost_usd": out["cost_usd"],
        "model_used": out["model_used"],
        "created_at": now_iso,
    })
    return TranslateResponse(
        conclusion_id=conclusion_id, source_language=source_lang, target_language=target,
        text=out["text"], cache_hit=False,
        input_tokens=out["input_tokens"], output_tokens=out["output_tokens"],
        latency_ms=out["latency_ms"], cost_usd=out["cost_usd"], model_used=out["model_used"],
    )


# --------------------------------------------------------------------------
# /api/providers — advertise which model slots are LIVE vs mocked
# --------------------------------------------------------------------------

@api_router.get("/providers")
async def get_providers():
    return {"providers": provider_status()}


@api_router.get("/providers/specs")
async def get_provider_specs():
    """Full slot list — including Coming Soon / Premium — for the frontend."""
    return {"providers": all_provider_specs()}


@api_router.get("/plans")
async def get_plans():
    """Return the plan catalog. UI can advertise plans without knowing the entitlement rules.

    Only FREE is active today. PREMIUM and BYOK are advertised as `available: false`
    so the UI can render "Coming Soon" chips without hardcoding any plan logic.
    """
    active_plan = Plan.FREE.value
    plans_payload = []
    for plan_enum, ents in PLAN_ENTITLEMENTS.items():
        plans_payload.append({
            "id": plan_enum.value,
            "available": plan_enum == Plan.FREE,
            "allowed_provider_ids": sorted(ents.allowed_provider_ids),
            "daily_compare_limit": ents.daily_compare_limit,
            "can_use_own_keys": ents.can_use_own_keys,
            "priority": ents.priority,
        })
    return {"active_plan": active_plan, "plans": plans_payload}


# --------------------------------------------------------------------------
# Identity endpoints — used by the frontend to discover the caller's plan
# and by admins to change a user's plan without a UI.
# --------------------------------------------------------------------------

@api_router.get("/me")
async def get_me(identity: IdentityContext = Depends(get_identity)):
    """Return the caller's plan + entitlements.

    Anonymous callers get the FREE plan. When real auth ships, this endpoint
    will start returning email / profile data too; the current fields will
    remain stable so the frontend never breaks.
    """
    ents = identity.entitlements
    return {
        "user_id": identity.user_id,
        "is_anonymous": identity.is_anonymous,
        "plan": identity.plan.value,
        "entitlements": {
            "allowed_provider_ids": sorted(ents.allowed_provider_ids),
            "daily_compare_limit": ents.daily_compare_limit,
            "can_use_own_keys": ents.can_use_own_keys,
            "priority": ents.priority,
        },
    }


class PlanChangeRequest(BaseModel):
    plan: str


@api_router.post("/admin/users/{user_id}/plan", dependencies=[Depends(require_admin)])
async def admin_set_plan(user_id: str, req: PlanChangeRequest):
    """Admin-only: promote a user to premium/byok or demote back to free.

    Guarded by the `X-Admin-Token` header (matched against `ADMIN_TOKEN` env).
    No frontend UI hooks into this yet — it exists so operators can test
    Premium and BYOK end-to-end before billing ships.
    """
    if not user_id or len(user_id.strip()) < 4:
        raise HTTPException(status_code=400, detail="user_id must be at least 4 characters")
    user_id = user_id.strip()
    try:
        new_plan = Plan(req.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown plan '{req.plan}'. Use one of: free, premium, byok.")
    now_iso = datetime.now(timezone.utc).isoformat()
    res = await db["users"].update_one(
        {"id": user_id},
        {"$set": {"plan": new_plan.value, "updated_at": now_iso},
         "$setOnInsert": {"id": user_id, "created_at": now_iso}},
        upsert=True,
    )
    return {
        "user_id": user_id,
        "plan": new_plan.value,
        "matched": res.matched_count,
        "upserted": bool(res.upserted_id),
    }


# --------------------------------------------------------------------------
# /api/queries/{id}/compare — real 4-model comparison
# --------------------------------------------------------------------------

class ModelResponse(BaseModel):
    id: str
    label: str
    codename: str
    provider: str
    text: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    is_mock: bool
    error: Optional[str] = None


class CompareResponse(BaseModel):
    query_id: str
    prompt: str
    responses: List[ModelResponse]
    live_count: int
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0


@api_router.post("/queries/{query_id}/compare", response_model=CompareResponse)
async def compare_query(query_id: str, identity: IdentityContext = Depends(get_identity)):
    doc = await db.queries.find_one({"id": query_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Query not found")

    prompt: str = doc["prompt"]
    strategy: str = doc.get("strategy", "balanced")
    audience: str = doc.get("audience", "professional")
    fmt: str = doc.get("format", "paragraph")

    system = (
        "You are one panellist in a multi-model AI consensus panel called AI Referee. "
        f"Audience: {audience}. Preferred format: {fmt}. Strategy: {strategy}. "
        "Answer the user's question directly and precisely — the panel synthesises multiple answers afterwards. "
        "Keep the answer self-contained; do not reference other panellists."
    )

    # Enforce per-user daily limit (anonymous callers are exempt).
    await enforce_daily_compare_limit(identity)

    # Anonymous callers keep the current MVP behaviour (only-live-providers).
    # Identified callers get plan-aware selection (Premium unlocks Claude, BYOK
    # can substitute user keys). Both paths NEVER call disabled providers.
    if identity.is_anonymous:
        providers = selected_providers()
    else:
        providers = selected_providers(user_id=identity.user_id, plan=identity.plan)
    if not providers:
        raise HTTPException(
            status_code=503,
            detail="No live AI providers are enabled. Enable ENABLE_OPENAI or ENABLE_GEMINI in backend/.env.",
        )
    tasks = [
        p.timed_generate(prompt, system, fallback_text_fn=fallback_for(p))
        for p in providers
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    responses: List[ModelResponse] = []
    live_count = 0
    total_cost = 0.0
    total_latency = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for p, r in zip(providers, results):
        if not r.is_mock:
            live_count += 1
        total_cost += r.cost_usd
        total_latency += r.latency_ms
        responses.append(ModelResponse(
            id=p.id,
            label=p.label,
            codename=r.model_used or p.codename,
            provider=p.provider_name,
            text=r.text,
            latency_ms=r.latency_ms,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            total_tokens=r.total_tokens,
            cost_usd=r.cost_usd,
            model_used=r.model_used,
            is_mock=r.is_mock,
            error=r.error,
        ))

        # Log EVERY provider invocation to Mongo — Task #7
        try:
            await db.compare_logs.insert_one({
                "id": str(uuid.uuid4()),
                "query_id": query_id,
                "prompt": prompt,
                "prompt_length": len(prompt),
                "response_length": len(r.text or ""),
                "provider_id": p.id,
                "provider_name": p.provider_name,
                "provider_label": p.label,
                "model_requested": p.codename,
                "model_used": r.model_used,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "latency_ms": r.latency_ms,
                "cost_usd": r.cost_usd,
                "is_mock": r.is_mock,
                "error": r.error,
                "created_at": now_iso,
            })
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning("Failed to persist compare log: %s", e)

    # Persist real responses on the cached conclusion so Smart Reuse serves the real answer next time.
    try:
        await db.conclusions.update_one(
            {"id": query_id},
            {"$set": {
                "responses": [r.model_dump() for r in responses],
                "live_count": live_count,
                "total_cost_usd": round(total_cost, 6),
                "generated_at": now_iso,
            }},
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("Failed to persist compare result: %s", e)

    return CompareResponse(
        query_id=query_id,
        prompt=prompt,
        responses=responses,
        live_count=live_count,
        total_cost_usd=round(total_cost, 6),
        total_latency_ms=total_latency,
    )


@api_router.get("/compare_logs")
async def list_compare_logs(query_id: Optional[str] = None, limit: int = 50):
    limit = max(1, min(limit, 200))
    q: dict = {}
    if query_id:
        q["query_id"] = query_id
    items = await db.compare_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"logs": items, "count": len(items)}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
