# AI Referee – Product Requirements & Session Log

## Original Problem Statement
Build AI Referee: a multi-model AI consensus platform that compares answers from 
multiple AI models and produces a single "Trusted Conclusion" based on agreement, 
factual consistency, reasoning quality and confidence.

## Core Requirements (static)
- Two ACTIVE providers today: **OpenAI + Google Gemini** (free tier).
- Three visible-but-disabled slots: **Grok** / **Mistral** (Coming Soon), 
  **Claude ★ Premium** (Coming Soon, fully wired).
- Backend must NEVER call disabled providers.
- Full multilingual pipeline (en/it/es/fr/de/pt):
   * Detect prompt language, run panel in the natural language.
   * Synthesise Trusted Conclusion in `answer_language` (user's UI language).
   * Cache per-language translations of the conclusion for Smart Reuse.
- Smart Reuse: semantic cache lookup BEFORE any AI call. `SMART_REUSE_THRESHOLD` env-tunable.
- API keys read from env only. Provider activation via ENABLE_X flags.
- Three-tier plan architecture: FREE (active), PREMIUM (Claude ready), BYOK (encrypted key store ready).
- Per-user plan resolution via `X-User-Id` header + rate limit; anonymous keeps MVP behaviour.
- Admin surface (`X-Admin-Token`) fail-closed.

## What's Implemented (Feb 2026)
### Core AI comparison
- [x] Provider registry with 5 slots + status labels.
- [x] Claude wired (`ENABLE_CLAUDE=true` + `ANTHROPIC_API_KEY` activates).
- [x] Compare endpoint 503s if 0 live providers; 429 on rate-limit.
- [x] `/api/providers`, `/api/providers/specs`, `/api/plans`, `/api/me`, `/api/admin/users/{id}/plan`.
### Multilingual pipeline (fixed this iteration)
- [x] `providers/synthesizer.py` — writes Trusted Conclusion in `answer_language`.
- [x] `QueryCreate.answer_language` persisted on the query record.
- [x] `CompareResponse` returns `trusted_conclusion`, `answer_language`, `synthesis_model`, `synthesis_latency_ms`, `synthesis_cost_usd`.
- [x] `GET /api/conclusions/{id}?lang=X` — translates + caches on read, powers Smart Reuse in target lang.
- [x] `conclusions.translations[lang]` sub-document for per-language cache.
- [x] Legacy conclusion rows without `trusted_conclusion` synthesise on-demand.
- [x] Home + Results + Reuse pages fully localised (no hardcoded English strings on user-visible chrome).
- [x] Removed self-match bug: `create_query` no longer seeds `conclusions`; only compare_query does.
### Plans + identity
- [x] `providers/plans.py`, `providers/key_source.py`, `services/user_keys.py` (Fernet, refuses without key).
- [x] `auth.py`: identity, admin guard, per-user daily rate limiter (atomic `$inc` + `ReturnDocument.AFTER`).

## Testing Coverage
- iteration_1.json — MVP scaffolding + reuse.
- iteration_2.json — Provider architecture + multilingual: 100% pass.
- iteration_3.json — Claude + plans + BYOK: 16/16.
- iteration_4.json — Identity/auth wiring: 14/14.
- iteration_5.json — Multilingual synthesis + i18n coverage: 11/11 backend + ~95% frontend (2 remaining strings fixed post-report).

## Backlog / Next
- P2: real auth (JWT/OAuth) — swap `get_identity` implementation, all routes stay stable.
- P2: Priority scheduling queue for Premium users.
- P2: Three-model consensus weighting (GPT + Gemini + Claude) — post-Premium.
- P3: BYOK: generate + install `USER_KEY_ENCRYPTION_KEY`; add "Connect your keys" settings UI (service methods ready).
- P4: Optional per-model response translation on Smart Reuse read (currently only Trusted Conclusion is translated; panellist responses show original language).
- P4: Split `server.py` (currently ~875 lines) into `routers/queries.py`, `routers/conclusions.py`, `routers/identity.py`.
