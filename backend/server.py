from fastapi import FastAPI, APIRouter, HTTPException, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import certifi
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

from providers import (  # noqa: E402
    ProviderResult,
    billable_provider_cost,
    provider_status,
    all_provider_specs,
    comparison_provider_specs,
    providers_for_execution,
    provider_unavailable_reason,
    provider_unavailable_status,
)
from providers.plans import PLAN_ENTITLEMENTS, Plan  # noqa: E402
from providers.embeddings import get_or_create_embedding, cosine, EMBED_MODEL  # noqa: E402
from providers.language import detect_language, normalize_prompt as lang_normalize, SUPPORTED as SUPPORTED_LANGS  # noqa: E402
from providers.translator import Translator, LANG_NAMES  # noqa: E402
from providers.synthesizer import Synthesizer, SynthesisFailure  # noqa: E402
from providers.conclusion_schema import (  # noqa: E402
    TrustedConclusion,
    eligible_synthesis_answers,
    normalize_stored_conclusion,
)
from providers.traceability_schema import (  # noqa: E402
    CitationRecord,
    TraceableClaim,
    extract_citations,
    merge_provider_citations,
    normalize_stored_traceability,
)
from auth import IdentityContext, get_identity, require_admin, enforce_daily_compare_limit  # noqa: E402

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(
    mongo_url,
    tls=True,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=30000,
)
db = client[os.environ["DB_NAME"]]

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
    # Language the user wants to see the Trusted Conclusion in. ISO-639-1 code.
    # Defaults to English so anonymous / legacy clients keep working unchanged.
    answer_language: Optional[str] = "en"


class QueryRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str
    goal: int
    detail: int
    audience: str
    format: str
    strategy: str = "balanced"
    answer_language: str = "en"
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
            {
                "embedding": {"$ne": None},
                "is_public": True,
                "execution_mode": "LIVE",
            },
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
        async for doc in db.conclusions.find(
            {"is_public": True, "execution_mode": "LIVE"},
            {"_id": 0},
        ).sort("created_at", -1).limit(300):
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

    # Legacy numeric guardrail. Trusted Conclusion 2.0 uses qualitative
    # confidence and therefore does not manufacture a replacement percentage.
    legacy_trust_score = best_doc.get("trust_score")
    if legacy_trust_score is not None and legacy_trust_score < 60:
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

    structured_confidence = (
        (best_doc.get("trusted_conclusion_structured") or {}).get("confidence")
        or {}
    )
    structured_factors = structured_confidence.get("factors") or {}
    match = {
        "id": best_doc["id"],
        "prompt": best_doc["prompt"],
        "created_at": created.isoformat(),
        "age_days": age_days,
        "similarity": round(best_score * 100),
        "similarity_tier": tier,
        "match_method": best_method,
        "confidence": best_doc.get("confidence"),
        "consensus": best_doc.get("consensus"),
        "trust": best_doc.get("trust_score"),
        "confidence_level": structured_confidence.get("level"),
        "consensus_level": structured_factors.get("model_agreement"),
        "evidence_quality": structured_factors.get("evidence_quality"),
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
    return await _translate_or_fetch(conclusion_id, target)


@api_router.get("/conclusions/{conclusion_id}")
async def get_conclusion(conclusion_id: str, lang: str = "en"):
    """Return a cached Trusted Conclusion in `lang`.

    Used by the Smart Reuse / reused-mode path on the frontend so the reused
    answer is displayed in the user's selected interface language, not the
    language of the original comparison.
    """
    target = (lang or "en").lower()
    resp = await _translate_or_fetch(conclusion_id, target)
    doc = await db.conclusions.find_one({"id": conclusion_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Conclusion not found")

    translations = doc.get("translations") or {}
    translated_entry = translations.get(target) or {}
    structured_candidate = translated_entry.get("structured_conclusion")
    if not isinstance(structured_candidate, dict):
        stored_language = doc.get("trusted_conclusion_language")
        if stored_language == target:
            structured_candidate = doc.get("trusted_conclusion_structured")
    structured, schema_version = normalize_stored_conclusion(
        {"trusted_conclusion_structured": structured_candidate}
    )
    claims: list[dict] = []
    citations: list[dict] = []
    claim_schema_version = "legacy"
    stored_language = doc.get("trusted_conclusion_language")
    if stored_language == target:
        claims, citations, claim_schema_version = normalize_stored_traceability(doc)
    default_status = "SUCCESS" if structured else ("LEGACY" if resp.text else "FAILED")
    stored_claim_status = str(doc.get("claim_analysis_status") or "").upper()
    if stored_claim_status == "FAILED":
        response_claim_status = "FAILED"
        response_claim_error = (
            doc.get("claim_analysis_error")
            or "Claim traceability is unavailable."
        )
    elif claim_schema_version == "3.0":
        response_claim_status = stored_claim_status or "SUCCESS"
        response_claim_error = doc.get("claim_analysis_error")
    else:
        response_claim_status = "NOT_AVAILABLE"
        response_claim_error = None
    return {
        "id": conclusion_id,
        "language": resp.target_language,
        "source_language": resp.source_language,
        "trusted_conclusion": resp.text,
        "trusted_conclusion_structured": structured,
        "conclusion_schema_version": schema_version,
        "synthesis_status": doc.get("synthesis_status") or default_status,
        "synthesis_error": doc.get("synthesis_error"),
        "execution_mode": doc.get("execution_mode", "LIVE"),
        "provider_statuses": doc.get("provider_statuses") or [],
        "claims": claims,
        "citations": citations,
        "claim_schema_version": claim_schema_version,
        "claim_analysis_status": response_claim_status,
        "claim_analysis_error": response_claim_error,
        "cache_hit": resp.cache_hit,
        "model_used": resp.model_used,
    }


async def _translate_or_fetch(conclusion_id: str, target: str) -> "TranslateResponse":
    doc = await db.conclusions.find_one({"id": conclusion_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Conclusion not found")
    source_lang = doc.get("trusted_conclusion_language") or doc.get("language", "en")
    source_version = doc.get("version", 1)

    # 1) Fast paths — the conclusion is already stored in the target language.
    body = doc.get("trusted_conclusion") or ""
    translations = doc.get("translations") or {}
    # 1a) Prefer a language-keyed translation cache on the conclusion itself.
    if target in translations and translations[target].get("text"):
        return TranslateResponse(
            conclusion_id=conclusion_id, source_language=source_lang, target_language=target,
            text=translations[target]["text"], cache_hit=True,
            input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0.0,
            model_used=translations[target].get("model", ""),
        )
    # 1b) Same-language body — no translation cost.
    if source_lang == target and body:
        return TranslateResponse(
            conclusion_id=conclusion_id, source_language=source_lang, target_language=target,
            text=body, cache_hit=True,
            input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0.0, model_used="none",
        )

    # 2) Legacy translation cache (kept for backwards compatibility).
    cache_key = {"conclusion_id": conclusion_id, "target_language": target, "source_version": source_version}
    cached = await db.translation_cache.find_one(cache_key, {"_id": 0})
    if cached:
        return TranslateResponse(
            conclusion_id=conclusion_id, source_language=source_lang, target_language=target,
            text=cached["text"], cache_hit=True,
            input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0.0, model_used=cached.get("model_used", ""),
        )

    # 3) Real translation call — ONLY the final conclusion body.
    if not body:
        # Never manufacture structured sections while reading a legacy row.
        # Return an explicit empty result for records with no stored text.
        return TranslateResponse(
            conclusion_id=conclusion_id, source_language=source_lang, target_language=target,
            text="", cache_hit=False,
            input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0.0, model_used="none",
        )
    tr = Translator()
    if not tr.available:
        raise HTTPException(status_code=503, detail="No translator configured (OPENAI_API_KEY missing).")
    out = await tr.translate(body, target_lang=target, source_lang=source_lang)

    # 4) Save to both caches so future reads are instant.
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
    await db.conclusions.update_one(
        {"id": conclusion_id},
        {"$set": {f"translations.{target}": {
            "text": out["text"], "model": out["model_used"], "generated_at": now_iso,
        }}},
    )
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
    provider_status: str
    execution_mode: str
    provider_error: Optional[str] = None
    provider_latency: int
    provider_name: str
    provider_response_id: str
    citations: List[CitationRecord] = Field(default_factory=list)


class CompareResponse(BaseModel):
    query_id: str
    prompt: str
    responses: List[ModelResponse]
    execution_mode: str
    live_count: int
    failed_count: int = 0
    mock_count: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
    # Backward-compatible text plus the validated 2.0 contract.
    trusted_conclusion: str = ""
    trusted_conclusion_structured: Optional[TrustedConclusion] = None
    conclusion_schema_version: Optional[str] = None
    synthesis_status: str = "FAILED"
    synthesis_error: Optional[str] = None
    answer_language: str = "en"
    synthesis_model: str = ""
    synthesis_latency_ms: int = 0
    synthesis_cost_usd: float = 0.0
    claims: List[TraceableClaim] = Field(default_factory=list)
    citations: List[CitationRecord] = Field(default_factory=list)
    claim_schema_version: Optional[str] = None
    claim_analysis_status: str = "FAILED"
    claim_analysis_error: Optional[str] = None


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

    if identity.is_anonymous:
        execution_mode, providers = providers_for_execution()
    else:
        execution_mode, providers = providers_for_execution(
            user_id=identity.user_id,
            plan=identity.plan,
        )

    # Every integrated FREE provider is discovered from the registry. Missing
    # optional providers remain visible as DISABLED records.
    expected_specs = comparison_provider_specs()
    providers_by_id = {
        provider.id: provider
        for provider in providers
        if provider.id in {spec["id"] for spec in expected_specs}
    }
    callable_providers = [
        providers_by_id[spec["id"]]
        for spec in expected_specs
        if spec["id"] in providers_by_id
    ]
    generated = await asyncio.gather(
        *(provider.timed_generate(prompt, system) for provider in callable_providers),
        return_exceptions=False,
    )
    generated_by_id = {
        provider.id: result
        for provider, result in zip(callable_providers, generated)
    }

    responses: List[ModelResponse] = []
    live_count = 0
    failed_count = 0
    mock_count = 0
    total_cost = 0.0
    total_latency = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for spec in expected_specs:
        provider = providers_by_id.get(spec["id"])
        result = generated_by_id.get(spec["id"])
        if result is None:
            result = ProviderResult(
                text="",
                provider_status=provider_unavailable_status(spec["id"]),
                error=provider_unavailable_reason(spec["id"]),
            )

        # Defence in depth: even a misconfigured provider cannot leak mock
        # content into a LIVE execution.
        if execution_mode == "LIVE" and (
            result.provider_status == "MOCK" or result.is_mock
        ):
            result = ProviderResult(
                text="",
                latency_ms=result.latency_ms,
                provider_status="FAILED",
                error="Mock content was blocked in LIVE execution mode.",
            )

        status = result.provider_status
        if status == "LIVE":
            live_count += 1
        elif status == "MOCK":
            mock_count += 1
        elif status == "TIMEOUT":
            failed_count += 1
            result.text = ""
            result.is_mock = False
        elif status == "DISABLED":
            result.text = ""
            result.is_mock = False
        else:
            status = "FAILED"
            failed_count += 1
            result.text = ""
            result.is_mock = False

        # Only a usable LIVE/DEMO answer contributes to the displayed total.
        # Failed, timed-out and disabled providers expose zero cost even if a
        # malformed adapter result accidentally carried a stale value.
        result.cost_usd = billable_provider_cost(result, status)
        total_cost += result.cost_usd
        total_latency += result.latency_ms
        provider_key = spec["provider_key"]
        try:
            provider_citations = extract_citations(
                result.text,
                provider_key,
                result.citation_metadata,
            ) if status in ("LIVE", "MOCK") else []
        except Exception as exc:  # Citation extraction must not fail compare.
            logging.getLogger(__name__).warning(
                "Citation extraction failed for %s: %s",
                spec["id"],
                type(exc).__name__,
            )
            provider_citations = []
        responses.append(ModelResponse(
            id=spec["id"],
            label=spec["label"],
            codename=result.model_used or spec["codename"],
            provider=spec["provider"],
            text=result.text,
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            cost_usd=result.cost_usd,
            model_used=result.model_used,
            is_mock=status == "MOCK",
            error=result.error,
            provider_status=status,
            execution_mode=execution_mode,
            provider_error=result.error,
            provider_latency=result.latency_ms,
            provider_name=spec["provider"],
            provider_response_id=provider_key,
            citations=provider_citations,
        ))

        # Log EVERY provider invocation to Mongo — Task #7
        try:
            await db.compare_logs.insert_one({
                "id": str(uuid.uuid4()),
                "query_id": query_id,
                "prompt": prompt,
                "prompt_length": len(prompt),
                "response_length": len(result.text or ""),
                "provider_id": spec["id"],
                "provider_name": spec["provider"],
                "provider_label": spec["label"],
                "model_requested": spec["codename"],
                "model_used": result.model_used,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "latency_ms": result.latency_ms,
                "cost_usd": result.cost_usd,
                "is_mock": status == "MOCK",
                "provider_status": status,
                "execution_mode": execution_mode,
                "error": result.error,
                "citation_count": len(provider_citations),
                "created_at": now_iso,
            })
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).warning("Failed to persist compare log: %s", e)

    # Persist real responses on the cached conclusion so Smart Reuse serves the real answer next time.
    # --- Synthesise the Trusted Conclusion in the caller's language -----------
    # `answer_language` is stored on the query record (set by the frontend based on
    # the user's interface language). We fall back to detecting the language of the
    # prompt so callers that don't send an explicit language still get a localised
    # answer.
    target_lang = (doc.get("answer_language") or detect_language(prompt) or "en").lower()
    if target_lang not in SUPPORTED_LANGS:
        target_lang = "en"

    synth_text = ""
    synth_structured: Optional[dict] = None
    synth_schema_version: Optional[str] = None
    synthesis_status = "FAILED"
    synthesis_error: Optional[str] = None
    synthesis_repair_attempted = False
    synth_model_used = ""
    synth_latency_ms = 0
    synth_cost_usd = 0.0
    claims: list[dict] = []
    citations = merge_provider_citations(
        response.citations
        for response in responses
        if response.provider_status == (
            "MOCK" if execution_mode == "DEMO" else "LIVE"
        )
    )
    claim_schema_version: Optional[str] = None
    claim_analysis_status = "FAILED"
    claim_analysis_error: Optional[str] = None
    answers_for_synth = eligible_synthesis_answers(responses, execution_mode)
    if not answers_for_synth:
        synthesis_error = (
            "Trusted Conclusion is unavailable because no provider returned "
            "usable evidence."
        )
        claim_analysis_error = synthesis_error
    else:
        try:
            synth = Synthesizer()
            if not synth.available:
                raise SynthesisFailure(
                    "Trusted Conclusion is unavailable because the synthesis "
                    "provider is not configured."
                )
            if answers_for_synth:
                s = await synth.synthesize(
                    prompt,
                    answers_for_synth,
                    target_lang,
                    audience,
                    fmt,
                    execution_mode,
                )
                synth_text = s["text"]
                synth_structured = s["structured_conclusion"]
                synth_schema_version = s["schema_version"]
                synthesis_status = "SUCCESS"
                synthesis_repair_attempted = bool(s.get("repair_attempted"))
                synth_model_used = s["model_used"]
                synth_latency_ms = s["latency_ms"]
                synth_cost_usd = float(s.get("cost_usd") or 0.0)
                claims = s.get("claims") or []
                citations = s.get("citations") or citations
                claim_schema_version = s.get("claim_schema_version")
                claim_analysis_status = s.get(
                    "claim_analysis_status",
                    "FAILED",
                )
                claim_analysis_error = s.get("claim_analysis_error")
        except SynthesisFailure as exc:
            synthesis_error = str(exc)
            claim_analysis_error = synthesis_error
            logging.getLogger(__name__).warning(
                "Trusted Conclusion synthesis failed: %s",
                type(exc).__name__,
            )
        except Exception as exc:  # Defence in depth: never expose raw errors.
            synthesis_error = "Trusted Conclusion synthesis failed unexpectedly."
            claim_analysis_error = (
                "Claim traceability analysis failed unexpectedly."
            )
            logging.getLogger(__name__).warning(
                "Unexpected Trusted Conclusion failure: %s",
                type(exc).__name__,
            )

    # Persist the synthesised conclusion so Smart Reuse can serve it later.
    # This is now an UPSERT — the conclusions row is created ONLY after a real
    # comparison has produced a Trusted Conclusion. Storing at create_query
    # time caused the very same row to self-match on the next /queries/match.
    q_topic = classify_topic(prompt)
    q_lang = detect_language(prompt)
    q_vec = None
    q_embed_model = None
    if q_topic in ("technical", "stable"):
        vec, embed_meta = await get_or_create_embedding(db, prompt)
        q_vec = list(vec) if vec is not None else None
        q_embed_model = embed_meta.get("model")
    provider_statuses = [
        {
            "id": response.id,
            "provider_name": response.provider_name,
            "provider_status": response.provider_status,
        }
        for response in responses
    ]
    try:
        await db.conclusions.update_one(
            {"id": query_id},
            {
                "$set": {
                    "responses": [r.model_dump() for r in responses],
                    "execution_mode": execution_mode,
                    "provider_statuses": provider_statuses,
                    "live_count": live_count,
                    "total_cost_usd": round(total_cost, 6),
                    "generated_at": now_iso,
                    "conclusion_created_at": now_iso,
                    "trusted_conclusion": synth_text,
                    "trusted_conclusion_structured": synth_structured,
                    "conclusion_schema_version": synth_schema_version,
                    "trusted_conclusion_language": target_lang,
                    "synthesis_status": synthesis_status,
                    "synthesis_error": synthesis_error,
                    "synthesis_repair_attempted": synthesis_repair_attempted,
                    "synthesis_model": synth_model_used,
                    "claims": claims,
                    "citations": citations,
                    "claim_schema_version": claim_schema_version,
                    "claim_analysis_status": claim_analysis_status,
                    "claim_analysis_error": claim_analysis_error,
                    "is_public": (
                        execution_mode == "LIVE"
                        and synthesis_status == "SUCCESS"
                        and bool(synth_structured)
                        and q_topic in ("technical", "stable")
                    ),
                    # Multilingual reuse cache: keyed by language so subsequent
                    # readers in the same language pay no translation cost.
                    f"translations.{target_lang}": {
                        "text": synth_text,
                        "structured_conclusion": synth_structured,
                        "schema_version": synth_schema_version,
                        "claims": claims,
                        "citations": citations,
                        "claim_schema_version": claim_schema_version,
                        "claim_analysis_status": claim_analysis_status,
                        "claim_analysis_error": claim_analysis_error,
                        "model": synth_model_used,
                        "generated_at": now_iso,
                    },
                },
                "$setOnInsert": {
                    "id": query_id,
                    "prompt": prompt,
                    "prompt_norm": normalize_prompt(prompt),
                    "prompt_tokens": list(tokens_of(prompt)),
                    "topic": q_topic,
                    "language": q_lang,
                    # Cacheable topics only. `is_public` gates whether Smart Reuse
                    # searches this row on subsequent matches.
                    "is_time_sensitive": q_topic == "news",
                    "category": "stable" if q_topic == "stable" else ("technical" if q_topic == "technical" else q_topic),
                    "embedding": q_vec,
                    "embedding_model": q_embed_model,
                    "audience": audience,
                    "format": fmt,
                    "created_at": now_iso,
                },
            },
            upsert=True,
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("Failed to persist compare result: %s", e)

    return CompareResponse(
        query_id=query_id,
        prompt=prompt,
        responses=responses,
        execution_mode=execution_mode,
        live_count=live_count,
        failed_count=failed_count,
        mock_count=mock_count,
        total_cost_usd=round(total_cost + synth_cost_usd, 6),
        total_latency_ms=total_latency + synth_latency_ms,
        trusted_conclusion=synth_text,
        trusted_conclusion_structured=synth_structured,
        conclusion_schema_version=synth_schema_version,
        synthesis_status=synthesis_status,
        synthesis_error=synthesis_error,
        answer_language=target_lang,
        synthesis_model=synth_model_used,
        synthesis_latency_ms=synth_latency_ms,
        synthesis_cost_usd=round(synth_cost_usd, 6),
        claims=claims,
        citations=citations,
        claim_schema_version=claim_schema_version,
        claim_analysis_status=claim_analysis_status,
        claim_analysis_error=claim_analysis_error,
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
