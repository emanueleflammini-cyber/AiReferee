# AI Referee — PRD

## Original Problem Statement
Build **AI Referee** — the first **AI Consensus Platform**. Not another chatbot. Instead of trusting a single AI, Referee sends a question to multiple models, analyses where they agree/disagree, and generates one transparent Trusted Conclusion. Never claims absolute truth — supports better-informed decisions via transparent consensus.

## User Positioning
- Hero: "One Question. Multiple AI Minds. One Trusted Conclusion."
- Pitch: "The first AI Consensus Platform that combines the best reasoning from multiple AI models into one transparent answer."
- Aesthetic: Apple / Linear / OpenAI / Perplexity. White / dark navy / electric blue. Glassmorphism, soft blue glow, smooth motion.

## Architecture
- **Frontend**: React 19, React Router 7, TailwindCSS, shadcn/ui, framer-motion, sonner, lucide-react.
- **Backend**: FastAPI + Motor (MongoDB), `/api` prefix.
- **State**: `QueryProvider` context (prompt, goal, detail, audience, format, strategy).

## Implemented (2026-02)
### Homepage `/`
- Hero: title, subtitle "One Question. / Multiple AI Minds. / One Trusted Conclusion.", pitch line.
- Ask textarea with autosize + ⌘/Ctrl+Enter shortcut.
- Filters: Response Goal + Detail Level sliders (with dynamic hint labels), Audience & Format pills.
- **Conclusion Strategy** section with 5 selectable cards: Maximum Accuracy, Balanced, Creative Thinking, Critical Analysis, Fast Response.
- **Generate Conclusion** primary CTA (renamed from Compare AIs).
- **How It Works** — 7-step visual workflow: Question → Multiple AI Models → Consensus Analysis → Evidence Review → Trusted Conclusion → Challenge Conclusion → Updated Conclusion. Numbered 01-07 with chevron connectors.
- **Supported Models** — 6 branded chips: ChatGPT, Gemini, Claude, Grok, Mistral, DeepSeek + "More models coming soon."
- Trust strip footer tiles.

### Results `/`
- Phased loading experience:
  1. `models` phase — each of 4 models (ChatGPT, Claude, Gemini, Grok) staggers from **Thinking…** → **Complete**.
  2. `analysis` phase — 7 Consensus Analysis messages tick off ("Comparing answers…" through "Preparing final conclusion…").
  3. `reveal` phase.
- Three top meters: Confidence, Consensus Level, Trust.
- 4 model cards with brand-color initials, latency & token stats.
- Three lists: Key Agreements, Key Disagreements, Remaining Uncertainty.
- **Trusted Conclusion** premium card (renamed from Super Answer) with animated Confidence + Consensus Level bars, main body, and a **Why this Conclusion?** transparency block.
- **Challenge Conclusion** button that plays a 6-step challenge animation, then reveals a strengthened outcome: **82% → 94%** with findings list. Confidence updates live in the meter and CTA footer.
- **Model Contribution** horizontal bar chart (34/28/23/15%) with animated fills.
- Transparency note verbatim.
- See Full Debate CTA to `/debate`.

### Debate `/debate`
- Chat-style thread across the 4 models with brand-colored bubbles + avatars, legend chips, verdict banner.

### Backend
- `POST /api/queries` accepts `{prompt, goal, detail, audience, format, strategy}` — strategy defaults to `balanced`.
- `GET /api/queries?limit=N`, `GET /api/queries/{id}`.
- `POST /api/status`, `GET /api/status` for infra checks.

## Testing
- Iteration 1: backend 100%, frontend 97% (harness-only quirks).
- Iteration 2: backend 100% (strategy field verified). Frontend verified visually + Playwright selector checks for `challenge-outcome`, `transparency-note`, `contribution-card` all True; every new section (strategy, workflow, supported models, phased loading, trusted-conclusion, model contribution) captured in screenshots.

## Prioritized Backlog

### P0 — Real intelligence
- Wire actual models (GPT-5.4, Claude Sonnet 4.6, Gemini 3.1 Pro, Grok 3.0) behind `POST /api/queries/{id}/compare` — parallel calls, real consensus + confidence, real challenge round.
- Persist full results (per-model text, scores, contributions, challenge history, super answer) and hydrate `/results/{id}` and `/debate/{id}` with real data.
- Auth (Emergent Google OAuth) + per-user query history.

### P1
- Shareable `/results/{id}` links with auto-generated OG image previews (huge for social growth).
- Prompt library / saved presets (strategy + filter bundles).
- Real streaming for the "Thinking…" phase — swap the fake timers for token stream indicators.

### P2
- Team workspaces + collaborative challenges (comment on findings).
- Export Trusted Conclusion as PDF / Markdown / Notion block.
- Stripe billing — free (2 models) vs Pro (all 6, higher rate limits, challenge unlimited).
