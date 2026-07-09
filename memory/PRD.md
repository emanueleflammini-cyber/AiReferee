# AI Referee — PRD

## Original Problem Statement
Build a modern SaaS web application called **AI Referee** — NOT a chatbot. It compares answers from multiple AI models and generates one optimized "Super Answer" based on consensus. Premium UI inspired by Apple, OpenAI and Linear. White, dark navy and electric blue palette. Minimal, elegant, responsive, mobile-first.

Homepage: `AI Referee` title, subtitle "One Question. Multiple AIs. One Super Answer.", "Ask anything..." textarea, filters (Response Goal slider Accuracy↔Creativity, Detail Level slider Quick↔Deep, Audience pills Beginner/Professional/Expert, Output Format pills Paragraph/Bullet List/Table/Step-by-step), and "Compare AIs" button.

Results page: 4 model cards (A/B/C/D) with placeholder responses, Consensus Score, Trust Score, Agreement Points, Disagreement Points, premium Super Answer card, "See Full Debate" button.

Debate page: chat-style back-and-forth between models.

**Do not implement AI integrations yet.**

## User Choices
- Backend saves queries to MongoDB (for later real-AI wiring)
- Modern geometric fonts (Geist)
- Rich micro-interactions with framer-motion
- Chat-style group debate
- Premium wordmark: minimalist Shield + Neural Network icon in white / dark navy / electric blue

## Architecture
- **Frontend**: React 19, React Router 7, TailwindCSS, shadcn/ui, framer-motion, sonner, lucide-react.
- **Backend**: FastAPI + Motor (MongoDB), routes prefixed with `/api`.
- **State**: `QueryProvider` React Context carries the user's prompt + filters across `/`, `/results`, `/debate`.
- **Data**: Static placeholder responses in `/app/frontend/src/lib/mockData.js` (Nova-1, Ember-3, Prism-2, Kairo-X).

## Implemented (2026-02)
- Home page (`/`) — Logo, hero, "Ask anything" textarea with autosize, two custom-styled sliders (Response Goal, Detail Level), Audience + Format pill groups, "Compare AIs" CTA with cmd/ctrl+enter shortcut, empty-prompt toast validation, feature trust strip.
- Results page (`/results`) — Question header, Consensus + Trust score pills, 2x2 grid of 4 Model cards with color-coded accent bars and latency/token stats, Agreement/Disagreement lists, premium **Super Answer** card with cyan top-glow, "See Full Debate" primary CTA.
- Debate page (`/debate`) — Chat-style thread with per-model color-tinted bubbles + circular avatars, model legend chips, verdict banner that returns to `/results`.
- Backend endpoints: `GET /api/`, `POST /api/queries`, `GET /api/queries?limit=N`, `GET /api/queries/{id}`, `POST /api/status`, `GET /api/status`.
- Design system: dark navy `#060A14` base, surface `#0B1120`, electric blue `#00E5FF`, primary blue `#0066FF`, per-model accents (`#00E5FF`, `#10B981`, `#F59E0B`, `#F43F5E`). Geist / Geist Mono fonts. Grain + grid + radial glow backgrounds. Sonner dark toasts.

## Testing (iteration 1)
- Backend: 100% (6/6 API checks).
- Frontend: 97% — all critical flows pass (Home → Results → Debate, empty prompt validation, filter toggles, mobile viewport).
- 2 LOW-priority items are Playwright-only quirks (card-model-a visibility flag, keyboard slider nav) — content renders correctly for real users.

## Prioritized Backlog

### P0 — Next
- Wire real AI providers (GPT-5.4, Claude Sonnet 4.6, Gemini 3.1 Pro, one more) behind `/api/queries/{id}/compare` — stream responses, compute real consensus.
- Persist full results (per-model text, scores, super answer, debate transcript) per query and hydrate `/results/{id}` and `/debate/{id}`.
- Auth (Emergent Google OAuth or JWT) + per-user query history.

### P1
- Consensus dial visualization (radial chart) and per-model confidence bars.
- Share links for `/results/{id}` with OG image preview.
- Prompt library / recent queries in nav.

### P2
- Team workspaces + saved presets (goal/detail/audience/format bundles).
- Export Super Answer as PDF/Markdown.
- Billing (Stripe) — free tier + Pro tier for premium models.
