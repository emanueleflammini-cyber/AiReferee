# AI Referee – Product Requirements & Session Log

## Original Problem Statement
Build AI Referee: a multi-model AI consensus platform that compares answers from 
multiple AI models and produces a single "Trusted Conclusion" based on agreement, 
factual consistency, reasoning quality and confidence.

## Core Requirements (static)
- Two ACTIVE providers today: **OpenAI + Google Gemini** (free tier).
- Three visible-but-disabled slots: **Grok** (Coming Soon), **Mistral** (Coming Soon), 
  **Claude ★ Premium** (Coming Soon).
- Backend must NEVER call disabled providers. No mocks masquerading as live answers.
- Multilingual UI (en/it/es/fr/de/pt) with persistent user choice.
- Smart Reuse: semantic cache lookup BEFORE any AI call; translate final answer only.
- API keys read from env only. Provider activation via ENABLE_X flags.

## What's Implemented (Feb 2026)
- [x] Provider registry with 5 slots + status labels (live / coming_soon / premium_coming_soon).
- [x] `selected_providers()` returns only live providers; compare endpoint 503s if 0 live.
- [x] `/api/providers` & `/api/providers/specs` expose full slot metadata to the UI.
- [x] Home Supported-Models grid renders LIVE / COMING SOON / PREMIUM · COMING SOON badges.
- [x] Results page renders 5 cards (2 live + 3 Coming Soon placeholders) with premium star for Claude.
- [x] i18n locale system with per-language JSON + persistent language selector.
- [x] Settings page uses `useI18n()` for all preference cards + hints.
- [x] Smart Reuse cache with semantic embeddings; multilingual conclusion translation.
- [x] Fallback chain: Gemini → OpenAI rescue → hard error (no fake mocks).
- [x] `savings` payload now scales with live provider count (was hardcoded 4).

## Testing Coverage
- iteration_1.json — MVP scaffolding + reuse system.
- iteration_2.json — 100% pass on provider architecture + multilingual + no leakage.

## Backlog / Next
### P1 (unlocked by architecture)
- Wire real Claude when Premium billing lands (`ENABLE_CLAUDE=true` + key).
- Wire Grok (xAI) when API pricing stabilises.
- Wire Mistral (Large 2) — provider spec ready.

### P2 (product polish)
- Persist Smart Reuse policy per user across devices (currently localStorage only).
- Raise Jaccard fallback threshold in `providers/embeddings.py` (0.55 → 0.65) to reduce 
  overly-lax matches across broad technical topics.
- Add per-provider health page / uptime monitor.

### P3
- Community-voted Trusted Conclusions.
- Debate replay export (share link).
