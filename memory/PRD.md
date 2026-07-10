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
- Three-tier plan architecture prepared: FREE, PREMIUM, BYOK.

## What's Implemented (Feb 2026)
- [x] Provider registry with 5 slots + status labels (live / coming_soon / premium_coming_soon).
- [x] Claude (Anthropic) fully wired — activation requires ONLY: ENABLE_CLAUDE=true + ANTHROPIC_API_KEY. Zero code change.
- [x] `selected_providers()` returns only live providers; compare endpoint 503s if 0 live.
- [x] `/api/providers`, `/api/providers/specs`, `/api/plans` — full slot & plan metadata for the UI.
- [x] Home Supported-Models grid renders LIVE / COMING SOON / PREMIUM · COMING SOON badges.
- [x] Results page renders 5 cards (2 live + 3 Coming Soon placeholders) with premium star for Claude.
- [x] i18n locale system with per-language JSON + persistent language selector.
- [x] Smart Reuse cache with semantic embeddings; multilingual conclusion translation.
- [x] `SMART_REUSE_THRESHOLD` env-configurable (default 0.55).
- [x] Fallback chain: Gemini → OpenAI rescue → hard error (no fake mocks).
- [x] Savings payload scales with live provider count.

### Business plan scaffolding
- [x] `providers/plans.py` — FREE / PREMIUM / BYOK entitlements.
- [x] `providers/key_source.py` — plan-aware `resolve_api_key(provider_id, user_id, plan)` (never logs raw keys).
- [x] `services/user_keys.py` — encrypted user-key store (Fernet). Refuses if `USER_KEY_ENCRYPTION_KEY` unset.
- [x] `registry.selected_providers(user_id, plan)` — BYOK-aware, default path unchanged (only OpenAI + Gemini).

## Testing Coverage
- iteration_1.json — MVP scaffolding + reuse system.
- iteration_2.json — Provider architecture + multilingual: 100% pass, no leakage.
- iteration_3.json — Claude wiring + plans + SMART_REUSE_THRESHOLD + BYOK abstraction: 16/16 pass.

## Backlog / Next
### P1 (unlocked)
- Claude activation: flip `ENABLE_CLAUDE=true` + add Anthropic key. No further code needed.
- Grok / Mistral: implement their providers when API pricing stabilises (registry slot ready).

### P2 (Premium launch)
- Premium Waitlist CTA on Claude chip (roadmap item — deferred per user request).
- Wire `active_plan` to a signed-in user + per-plan rate limiting.
- Priority scheduling queue for Premium users.
- Three-model consensus tuning (GPT + Gemini + Claude) — weighting logic.

### P3 (BYOK launch)
- User settings UI to add/rotate/delete provider keys (endpoints exist as service methods).
- Set `USER_KEY_ENCRYPTION_KEY` (Fernet-generated) in prod.
- One-time purchase billing (Stripe integration).
- Frontend indicator: "Powered by your key" badge on cards using a BYOK key.

### P4 (product polish)
- Raise Jaccard reuse threshold via `SMART_REUSE_THRESHOLD=0.65` after A/B test.
- Community-voted Trusted Conclusions.
- Debate replay export.
