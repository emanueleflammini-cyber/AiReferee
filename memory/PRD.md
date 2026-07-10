# AI Referee – Product Requirements & Session Log

## Original Problem Statement
Build AI Referee: a multi-model AI consensus platform that compares answers from 
multiple AI models and produces a single "Trusted Conclusion" based on agreement, 
factual consistency, reasoning quality and confidence.

## Core Requirements (static)
- Two ACTIVE providers today: **OpenAI + Google Gemini** (free tier).
- Three visible-but-disabled slots: **Grok** (Coming Soon), **Mistral** (Coming Soon), 
  **Claude ★ Premium** (Coming Soon, fully wired).
- Backend must NEVER call disabled providers. No mocks masquerading as live answers.
- Multilingual UI (en/it/es/fr/de/pt) with persistent user choice.
- Smart Reuse: semantic cache lookup BEFORE any AI call; translate final answer only.
- API keys read from env only. Provider activation via ENABLE_X flags.
- Three-tier plan architecture: FREE, PREMIUM, BYOK. FREE active; PREMIUM/BYOK ready.
- Per-user plan resolution via `X-User-Id` header; anonymous callers keep MVP behaviour.
- Fail-closed admin surface for plan management (no frontend UI).

## What's Implemented (Feb 2026)
- [x] Provider registry with 5 slots + status labels.
- [x] Claude wired — flip `ENABLE_CLAUDE=true` + `ANTHROPIC_API_KEY` to activate.
- [x] Compare endpoint 503s if 0 live providers.
- [x] `/api/providers`, `/api/providers/specs`, `/api/plans`, `/api/me`, `/api/admin/users/{id}/plan`.
- [x] Home + Results UI: LIVE / COMING SOON / PREMIUM · COMING SOON badges.
- [x] i18n locales (en/it/es/fr/de/pt) with persistent selector.
- [x] Smart Reuse: `SMART_REUSE_THRESHOLD` env-tunable, multilingual conclusion cache.
- [x] Fallback chain: Gemini → OpenAI rescue → hard error.
- [x] Savings payload scales with live provider count.
- [x] Plans/entitlements module.
- [x] Encrypted user-key store (Fernet), never-log-key discipline. BYOK backend-only.
- [x] Identity layer (`auth.py`): `X-User-Id` header → users collection upsert; anonymous → FREE.
- [x] Admin surface: fail-closed on unset `ADMIN_TOKEN`; 400 on invalid plan/user_id.
- [x] Per-user daily compare rate limit via `usage_events` collection (atomic $inc + ReturnDocument.AFTER).

## Testing Coverage
- iteration_1.json — MVP scaffolding + reuse system.
- iteration_2.json — Provider architecture + multilingual: 100% pass.
- iteration_3.json — Claude wiring + plans + SMART_REUSE_THRESHOLD + BYOK abstraction: 16/16.
- iteration_4.json — Identity/auth wiring: 14/14.

## Backlog / Next
### P1 (contest-safe additions)
- Ship the current stack for the contest — MVP is stable end-to-end.

### P2 (Premium launch)
- Real auth (JWT or OAuth) — swap `get_identity` implementation only, all routes stay stable.
- Priority scheduling queue for Premium users (has `priority` int already in entitlements).
- Three-model consensus tuning (GPT + Gemini + Claude) — weighting logic.
- Premium Waitlist CTA on Claude chip (roadmap — deferred per user request).
- Marketing plan cards driven by `/api/plans` (deferred per user request).

### P3 (BYOK launch)
- User settings UI to add/rotate/delete provider keys (service methods `set_user_key`/`delete_user_key` exist).
- Generate + install `USER_KEY_ENCRYPTION_KEY` (Fernet).
- One-time purchase billing (Stripe integration).
- Frontend "Powered by your key" badge on cards using a BYOK key.

### P4 (polish)
- Raise Jaccard reuse threshold via `SMART_REUSE_THRESHOLD=0.65` after A/B test.
- Community-voted Trusted Conclusions.
- Debate replay export.
