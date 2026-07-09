from fastapi import FastAPI, APIRouter, HTTPException
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

from providers import selected_providers, provider_status  # noqa: E402

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
}

SIM_THRESHOLD = 0.55


def normalize_prompt(p: str) -> str:
    p = (p or "").lower()
    p = re.sub(r"[^a-z0-9\s]", " ", p)
    p = re.sub(r"\s+", " ", p).strip()
    return p


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


class MatchResponse(BaseModel):
    policy: str          # reusable | never_reuse | always_refresh
    topic: str           # stable | technical | sensitive | news
    match: Optional[Dict[str, Any]] = None
    reason: str
    ttl_days: int


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

    # Cache a mock conclusion for the Smart Reuse system unless the topic
    # is never-reuse (news) or always-refresh (sensitive).
    topic = classify_topic(payload.prompt)
    if topic in ("technical", "stable"):
        await db.conclusions.insert_one({
            "id": record.id,
            "prompt": payload.prompt,
            "prompt_tokens": list(tokens_of(payload.prompt)),
            "topic": topic,
            "confidence": 82,
            "consensus": 87,
            "trust": 92,
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

    if topic == "news":
        return MatchResponse(
            policy="never_reuse",
            topic=topic,
            reason="News, prices, weather and current-event topics are never cached — this will be fetched fresh.",
            ttl_days=0,
        )
    if topic == "sensitive":
        return MatchResponse(
            policy="always_refresh",
            topic=topic,
            reason="Financial, legal and medical topics always run a fresh comparison for safety.",
            ttl_days=0,
        )

    # Look for a semantically-similar prior conclusion
    toks = tokens_of(prompt)
    now = datetime.now(timezone.utc)
    best_doc = None
    best_score = 0.0
    async for doc in db.conclusions.find({}, {"_id": 0}).sort("created_at", -1).limit(300):
        prev_toks = set(doc.get("prompt_tokens", []))
        score = jaccard(toks, prev_toks)
        if score > best_score:
            best_score = score
            best_doc = doc

    if best_doc is None or best_score < SIM_THRESHOLD:
        return MatchResponse(
            policy="reusable",
            topic=topic,
            reason="No similar prior conclusion in cache — this will be a fresh comparison.",
            ttl_days=ttl,
        )

    created = best_doc.get("created_at")
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    age = now - created
    age_days = max(0, age.days)
    if age_days > ttl:
        return MatchResponse(
            policy="reusable",
            topic=topic,
            reason=f"A prior conclusion exists but exceeds the {ttl}-day cache window for this topic.",
            ttl_days=ttl,
        )

    match = {
        "id": best_doc["id"],
        "prompt": best_doc["prompt"],
        "created_at": created.isoformat(),
        "age_days": age_days,
        "similarity": round(best_score * 100),
        "confidence": best_doc.get("confidence", 82),
        "consensus": best_doc.get("consensus", 87),
        "trust": best_doc.get("trust", 92),
        "topic": topic,
    }
    return MatchResponse(
        policy="reusable",
        topic=topic,
        match=match,
        reason=f"A similar prior conclusion ({match['similarity']}% match, {age_days}d old) is available for reuse.",
        ttl_days=ttl,
    )


# --------------------------------------------------------------------------
# /api/providers — advertise which model slots are LIVE vs mocked
# --------------------------------------------------------------------------

@api_router.get("/providers")
async def get_providers():
    return {"providers": provider_status()}


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
    tokens: int
    is_mock: bool
    error: Optional[str] = None


class CompareResponse(BaseModel):
    query_id: str
    prompt: str
    responses: List[ModelResponse]
    live_count: int


@api_router.post("/queries/{query_id}/compare", response_model=CompareResponse)
async def compare_query(query_id: str):
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

    providers = selected_providers()
    tasks = [p.timed_generate(prompt, system) for p in providers]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    responses: List[ModelResponse] = []
    live_count = 0
    for p, r in zip(providers, results):
        if not r.is_mock:
            live_count += 1
        responses.append(ModelResponse(
            id=p.id,
            label=p.label,
            codename=p.codename,
            provider=p.provider_name,
            text=r.text,
            latency_ms=r.latency_ms,
            tokens=r.tokens,
            is_mock=r.is_mock,
            error=r.error,
        ))

    # Persist the live model output onto the cached conclusion (if we have one for this query)
    # so future reuse can serve the *real* answer, not a mock.
    try:
        await db.conclusions.update_one(
            {"id": query_id},
            {"$set": {
                "responses": [r.model_dump() for r in responses],
                "live_count": live_count,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("Failed to persist compare result: %s", e)

    return CompareResponse(
        query_id=query_id,
        prompt=prompt,
        responses=responses,
        live_count=live_count,
    )


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
