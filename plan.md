# Cadre Support Bot — plan.md (working doc)

Support chatbot for Cadre (AI strategy & implementation consultancy). FastAPI + React (Vite) + LLM via openai SDK. Curated KB injected into the system prompt — no RAG, no db in v1. Architecture, rules and interfaces: CLAUDE.md (this file is the task list, that one is the law).

## Goal
A deployed public chatbot that answers Cadre's common inbound questions from the KB and hands off to a human (booking link: https://www.cadreai.com/contact) when it can't.

## Scope v1

In:
1. Q&A over the KB
2. Multiturn sessions, last 10 messages to the model
3. Fallback with booking link + optional name/email capture
4. Minimal React chat UI served by FastAPI, so it's one deploy
5. One-screen access-code gate: the deployed bot spends real credits per message, the gate keeps strangers from draining them

Out, on purpose:
1. RAG / vector db — nothing to retrieve at this size, it only adds latency and failure modes; the seam is ready (layer 4), adding it later = one new class
2. Redis — single-instance demo, interface ready in layer 5
3. Real auth (accounts, JWT) — overkill for a demo bot; rate limiting would be the first prod step
4. Dashboards / analytics / CRM — with more time
5. Runtime site crawling — the KB holds only the stable evergreen core; when the fast-changing content needs to come in, the crawl becomes the ingestion step of the RAG impl (crawl > chunk > embed > the layer 4 seam) in v2
6. Streaming responses — replies are short (~500 token cap), not worth the extra moving parts in v1

## Decisions already made (apply, don't reconsider)
1. LLM through API_KEY with the openai SDK + BASE_URL; model from env var, default a Claude haiku-tier model if possible. Upgrading or A/B-ing ANY provider's model = flip one env var
2. Can't answer → the model writes `<fallback reason=""/>` inside its reply; ai_service strips it and the API returns the fallback card. Chosen over tool calling: same behavior, fewer moving parts, and the parser is a plain function testable without the network
3. Behavior rules live in prompt_builder (layer 3), facts live in the KB (layer 4), the two files never mix — editing what the bot KNOWS never risks changing how it BEHAVES
4. Tests live where AI-generated code lies the most: offline pytest with a faked LLM client (coverage list: CLAUDE.md Testing)
5. The KB comes from Cadre's real website, every fact traceable to its source URL. Not in the KB = the bot falls back, never guesses
6. Honesty is checked, not assumed: prompt boundaries + fallback way out (prevention), grounding check on every answer degrading to verbatim KB text (detection), /verify-scenarios re-tests the 6 scenarios end to end
7. The KB is never edited as a reaction to a failing test. A fail means report the gap; the fix goes back through curation and Paola's review

## Phases

### Phase 1 — skeleton live (layers 2+6+7), BEFORE any AI code
- [x] app/config.py: pydantic-settings (API_KEY, BASE_URL, LLM_MODEL, ACCESS_CODE, MOCK_LLM=false, SESSION_TTL_SECONDS=3600, ENVIRONMENT, LOG_LEVEL) behind get_settings(); nothing else reads os.environ — done, lru_cache singleton, min_length=1 on the required fields
- [x] app/main.py: create_app() factory — fails fast if API_KEY missing, structlog configured, nothing runs at import time except create_app() — done, verified: empty API_KEY raises ValidationError at import
- [x] GET /health (no access code required) — done, lives in app/api/routes.py, curl returns {"status":"ok"} 200
- [x] Static mount serving frontend/dist (placeholder build for now) — done, stock Vite build mounted at /, warns if dist missing
- [x] Dockerfile, two stages: node builds the React app → python copies the static files and runs uvicorn on $PORT (never hardcoded) — done + .dockerignore; verified: image builds, container on PORT=10000 serves /health 200 and the UI
- [x] Render web service created in the dashboard (manual, one-time): connect repo, runtime Docker, env vars API_KEY / BASE_URL / LLM_MODEL / ACCESS_CODE
- [x] Checkpoint: /health returns 200 on the public onrender.com URL

### Phase 2 — core chat (4+3+5, then 2+1)
- [x] KB: Claude drafts docs/cadre-kb.md from https://www.cadreai.com/ — the COMPLETE evergreen core per CLAUDE.md layer 4, the file is the foundation data: home, about, each of the 4 service pages (Strategy, Leadership & Facilitation, Engineering, Agents), industries and departments as one-liners + link, booking/contact. Extract don't paraphrase, one section per topic with its source URL, never invent (if a page doesn't state it, it doesn't go in). STOP and show Paola the full diff for review BEFORE writing the file — her approval is what makes the KB trusted. The MANUALLY SOURCED section stays untouched. The 6 scenarios (portal access, AI Maturity Index, LLM choice / data security posture) are the coverage FLOOR, not the whole target; flag any scenario the site doesn't cover instead of inventing it — done: 14 sections drafted from the live site, reviewed and approved by Paola. Adversarially audited by 2 fresh subagents against every source page (all 26 URLs return 200): 15 findings fixed — 2 homepage service-card quotes re-attributed to their real source, 7 truncated department one-liners completed with the site's full wording, 4 inexact quotes corrected, 3 invented connective claims (portal access provisioning, "book a call", "provider-agnostic") replaced with site-supported wording. Site gaps stand: no portal access URL / Maturity Index scoring steps published, both route honestly to the contact link; `## --------` separator must be skipped by the knowledge.py parser
- [x] app/data/knowledge.py: load + parse sections into KnowledgeSection(id, title, content) at startup, fail fast on missing file or empty section — done: `## --------` separator skipped, slug ids, wired into create_app so startup fails fast; 14 sections load
- [x] app/data/repository.py: KnowledgeSource.retrieve(query) (static impl returns everything, query param is the RAG seam) + get_booking_link(). Only this file imports knowledge.py — done: KnowledgeSource ABC + StaticKnowledgeSource, lru_cache singleton behind get_knowledge_source()
- [x] app/core/prompt_builder.py: build_system_prompt(sections) = persona + sections + boundaries + fallback protocol; never imports app/data — done: local SectionLike Protocol keeps it decoupled, raises on empty sections, pytest guards the no-app/data-import rule
- [x] app/core/ai_service.py: openai SDK client pointed at BASE_URL, get_response(messages), fallback-marker parser (find, strip, return reason), AIUnavailableError / AIRateLimitError mapped from SDK errors, ~500 output-token cap, MOCK_LLM=true returns canned replies offline — done: AIService behind get_ai_service(), max_tokens=500 asserted in tests, mock mode builds no network client and "fallback" in the message triggers the canned fallback for UI click-through
- [x] app/sessions: Message/Session models, SessionStore ABC (create/get/save/delete), in-memory store (dict + lock + TTL check on read), SessionManager on top; store keeps full history — done: timestamps live in the store (models stay pure), save() refreshes the TTL, injectable clock makes expiry testable offline, get_session_manager() singleton
- [x] app/api: schemas (ChatRequest{message}, ChatResponse{chat_id, reply, fallback|null}), routes POST /api/v1/chat, POST /api/v1/chat/{id}/messages, GET /api/v1/chat/{id}; X-Access-Code check on all /api/v1/* (401 ACCESS_DENIED), trim to last 10 messages before core, map errors 502 / 429 / 404 UNKNOWN_CHAT, all errors {code, message} — done: gate is a router-level dependency (secrets.compare_digest), errors.py gives every error (incl. 422 INVALID_REQUEST) the {code, message} shape, fallback carries reason + booking_url; verified live with curl under MOCK_LLM=true
- [x] UI: Gate.jsx (code → sessionStorage), api.js (all fetches, X-Access-Code header, 401 → back to gate), App.jsx (messages, input, loading, error banner) — done (subagent): Cadre-branded (accent/sand palette from the site's own stylesheet), centered card, mobile-ready, no animations; failed sends restore the text into the input for retry; per Paola's mid-build note the bordered fallback card + "Book a call" button was pulled forward from phase 3 (name/email form still phase 3); npm run build + eslint clean, dist served by the running app
- [x] UI: refresh keeps the conversation — chat_id persisted in sessionStorage, history rehydrated on load via GET /api/v1/chat/{id} (expired id clears silently, 401 bounces to the gate); "New chat" header button drops the stored id so the next message starts a fresh session (Paola's request)
- [x] pytest: prompt contains KB + boundaries, marker parser, session TTL expiry, access gate 401, route status codes + error shape (TestClient, faked LLM client) — done: tests/test_api.py adds 12 route tests (gate, happy path, 10-message trim, fallback shape, 404/429/502/422 mapping) on top of the existing suites; 46 pass offline
- [ ] Checkpoint: multiturn chat works locally end to end (MOCK_LLM first, then real key), tests green

### Phase 3 — fallback + grounding check + polish (1+2+3)
- [ ] Grounding check in ai_service: second LLM call gets answer + KB sections → GROUNDED / UNGROUNDED. Ungrounded or check errored: ship the matching KB section verbatim (keyword match on section titles; no match → fallback card) and log it. No answer ships unchecked
- [ ] Fallback card in the UI: booking link + optional name/email form
- [ ] POST /api/v1/chat/{id}/contact {name, email}: store on the session + log
- [ ] UI error states: banner for 502/429, gate redirect on 401, loading state
- [ ] pytest: grounding verdict parser, KB section matcher, ungrounded degrade path, contact route
- [ ] README: setup, env vars, endpoint table
- [ ] Checkpoint: pytest green + reviewer subagent pass on the phase diff

### Phase 4 — verify (all layers)
- [ ] Full pytest suite green
- [ ] /verify-scenarios against the local running app with the real LLM (MOCK_LLM=false)
- [ ] Push → Render auto-deploys; confirm env vars (MOCK_LLM never set in Render)
- [ ] /verify-scenarios against the DEPLOYED URL — all 6 scenarios pass
- [ ] Record anything found in Known issues below

## Known issues
- Fallback card doesn't survive a page refresh: GET /api/v1/chat/{id} returns only role/content, so a rehydrated fallback reply renders as a plain bubble without the "Book a call" card (reviewer finding, 2026-07-18). Fix needs fallback state persisted on the session Message model + exposed in MessageOut — Paola to decide; natural fit for phase 3's fallback work

## With more time (v2)
- RAG over the unbounded content (articles, case studies, podcast, events): crawl > chunk > embed, dropped in behind the layer 4 retrieve(query) seam — callers unchanged
- Redis session store behind the SessionStore ABC — callers unchanged
- Real auth (accounts, JWT) replacing the access-code gate
- Dashboards / analytics / CRM handoff for the captured contacts
