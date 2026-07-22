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
6. In-memory rate limit: max 10 messages per minute, then a "try again later" error — the gate stops strangers, this stops one holder of the code from draining the credits

Out, on purpose:
1. RAG / vector db — nothing to retrieve at this size, it only adds latency and failure modes; the seam is ready (layer 4), adding it later = one new class
2. Redis — single-instance demo, interface ready in layer 5
3. Real auth (accounts, JWT) — overkill for a demo bot
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
- [x] Checkpoint: multiturn chat works locally end to end (MOCK_LLM first, then real key), tests green — done: MOCK_LLM click-through in phase 2; real-key multiturn verified in phase 4 (follow-up "which other industries besides that one?" on a live chat resolved the reference from context, every industry named matched the KB verbatim)

### Phase 3 — fallback + grounding check + polish (1+2+3)
- [x] Grounding check in ai_service: second LLM call gets answer + KB sections → GROUNDED / UNGROUNDED. Ungrounded or check errored: ship the matching KB section verbatim (keyword match on section titles; no match → fallback card) and log it. No answer ships unchecked — done: get_response(messages, sections), verdict capped at 8 tokens, fallback replies skip the check, check errors (incl. rate limit) degrade instead of raising, every degrade logged (ungrounded_reply / grounding_check_failed / ungrounded_degraded_to_*)
- [x] Fallback card in the UI: booking link + optional name/email form — done: FallbackCard.jsx (name+email form, sending/sent/error states, ACCESS_DENIED bounces to the gate), card also rebuilt on reload from persisted history
- [x] POST /api/v1/chat/{id}/contact {name, email}: store on the session + log — done: ContactRequest validates name non-empty + email format (422 INVALID_REQUEST), Session.contact via SessionManager.set_contact() (store writes stay behind save()), contact_captured logged; verified live with curl
- [x] UI error states: banner for 502/429, gate redirect on 401, loading state — done in phase 2's UI pass; verified this phase, gate redirect now shared (handleAccessDenied) with the contact form
- [x] pytest: grounding verdict parser, KB section matcher, ungrounded degrade path, contact route — done: 69 tests green offline (verdict parser incl. UNGROUNDED-contains-GROUNDED trap, matcher stopwords/best-overlap/no-match, degrade to KB verbatim + to fallback card, check-error degrade, contact 200/404/422/401, history carries fallback)
- [x] README: setup, env vars, endpoint table — done: root README.md with how-it-works, local run, env var table, endpoint + error-code tables, testing, deploy
- [x] Checkpoint: pytest green + reviewer subagent pass on the phase diff — done: reviewer found no blockers, layer boundaries hold; its one should-fix (verdicts like "NOT GROUNDED" slipped past the parser) fixed + tested; 70 tests green, UI lint + build clean, flow verified live with curl under MOCK_LLM

### Phase 4 — verify (all layers)
- [x] Full pytest suite green — 70 passed offline (.venv python)
- [x] /verify-scenarios against the local running app with the real LLM (MOCK_LLM=false) — 2026-07-17: 6/6 PASS. Each answer graded by an independent subagent that saw only the KB + the response text; all claims traced to KB lines (incl. contact email/phone, eight-pillar Maturity Index wording, black-box data claim). Scenario 6 returned the fallback card with booking link and wrote no poem. No fixes needed. Re-run 2026-07-18 after the markdown/auth/observability/contact-card changes: 6/6 PASS again (fresh judges; scenario 5's full 12-platform LLM list verified verbatim against the KB's "LLM Selection & Data Security" section), booking card auto-attached on every contact-recommending answer, scenario 6 still falls back with no poem
- [x] Push → Render auto-deploys; confirm env vars (MOCK_LLM never set in Render) — Paola's side
- [x] /verify-scenarios against the DEPLOYED URL — all 6 scenarios pass — blocked on the push above
- [x] Record anything found in Known issues below — nothing new found this run; the two open known issues below stand unchanged

### Phase 5 — in-memory rate limit (layer 2)
Scope: the gate stops strangers, this stops one code from flooding the bot. Layer 2 only — no new dep, no store, no change to core/sessions/KB.
- [x] app/api/rate_limit.py: fixed-window counter, max 10 messages per 60s, keyed per access code + client IP; dict + lock, entries dropped once their window has passed (same in-memory-with-a-lock shape as the session store, no new abstraction) — done: RateLimiter.check(key) raises the ApiError itself, injectable clock, get_rate_limiter() singleton; a rejected hit isn't counted so knocking can't extend the window
- [x] Wire it as a router dependency on the two message-sending routes only (POST /api/v1/chat, POST /api/v1/chat/{id}/messages) — reads (GET chat, auth, health) and the contact post stay unlimited — done: per-route `dependencies=[Depends(enforce_message_rate_limit)]`, verified live that /api/v1/auth still returns 200 while messages are blocked
- [x] errors.py / routes: over the limit → 429 `TOO_MANY_MESSAGES`, "You're sending messages too quickly. Try again later." Distinct from the existing 429 `RATE_LIMITED` (that one means the upstream LLM is busy) — the UI switches on the code, so the two must not collapse into one — done; errors.py needed no change: ApiError already gives every error the {code, message} shape and no file enumerates codes, so the limiter raises ApiError inline the way routes.py does
- [x] UI: the error banner shows the message for `TOO_MANY_MESSAGES` like the other 429; the failed text is restored into the input so the user can resend after the window — no code change needed: api.js rethrows any {code, message} body and App.jsx's send-failure path already banners err.message and restores the input for every code it doesn't special-case
- [x] pytest (tests/test_api_rate_limit.py): 10 messages pass and the 11th returns 429 with the {code, message} shape, a different access code isn't affected, the window resets (injected clock, no sleeps) — done: 8 tests; conftest gives each test its own limiter so the singleton doesn't leak across tests
- [x] Checkpoint: pytest green + curl the 11th message locally and show the real 429 body — 91 tests pass offline; live under MOCK_LLM messages 1-10 returned 200 and the 11th returned 429 {"code":"TOO_MANY_MESSAGES","message":"You're sending messages too quickly. Try again later."}

## Known issues
- ~~Fallback card doesn't survive a page refresh~~ — fixed in phase 3: Message.fallback_reason persisted on the session, MessageOut exposes fallback {reason, booking_url}, the UI rebuilds the card from history on reload
- Contact-form "sent" state is UI-local: after a page reload a fallback card shows the name/email form again even if details were already submitted (resubmitting just overwrites session.contact). Harmless for the demo, no analytics or other service connected.
- ~~tests/test_api.py sits right at the ~300-line limit; the next route test should split it (e.g. tests/test_api_contact.py) per the file-size rule~~ — done with the GET /api/v1/auth work: shared fixture moved to tests/conftest.py, gate + auth tests live in tests/test_api_auth.py, test_api.py back under the limit

## With more time (v2)
Every item below plugs into a layer that already exists, that's the point of the layer interfaces: growing means adding a piece, never rewiring. So this first V1 works as a foundation

1. RAG over the unbounded content (articles, case studies, podcast, events). Today the bot only knows the evergreen core. The growing content doesn't fit, so v2 adds a pipeline that crawls those pages on a schedule, splits them into chunks, and stores them in a vector db. Plugs into: layer 4's retrieve(query) already takes the user's question, a VectorKnowledgeSource implements the same method returning the most relevant chunks. prompt_builder, routes and UI never change.
2. Redis session store. Today conversations live in one server's memory: fine for a single instance, lost on restart, impossible to share across servers. Redis makes sessions survive restarts and lets many instances serve the same users, required for horizontal scaling, bc any server must be able to answer any chat. Plugs into: a RedisSessionStore implements the same four methods of the SessionStore contract (create/get/save/delete). SessionManager and routes don't change.
3. Real auth (accounts) replacing the access code gate. The gate is a basic lock, not identity. Accounts give each user an identity, which is what unlocks per user chat history, client-specific answers, and per-user limits. Plugs into: the gate is already a single dependency on the routes, swapping it for a token check swaps one function, and sessions gain an owner.
4. Contact handoff (CRM / email / Slack). Today a captured lead lands on the session and in the logs, proven end to end, but nobody gets notified. v2 routes it where the team works: email, a Slack ping, or the CRM.
5. Shared rate-limit counters. V1's limiter counts in one server's memory, so it resets on restart and each instance counts on its own. Moving the counter to Redis makes the limit hold across restarts and instances, and per-account limits become possible once accounts exist (3). Plugs into: the limiter is one dependency in layer 2, only its storage changes.
6. Streaming replies. Answers appear word by word instead of after a pause. Skipped in v1 bc replies are capped 500 tokens, so the pause is short. Plugs into: the LLM call is isolated in ai_service, streaming changes that one function plus the bubble rendering.
7. Golden QA eval in CI. The /verify-scenarios idea, automated: a bigger fixed question set runs on every push and fails the build if an answer loses grounding, prompt regressions get caught before deploy, not by a user. Plugs into: the skill and the judging pattern already exist; CI just runs them.
8. Observability stack (Grafana + alerts). The logs are already structured events carrying verdicts, durations, token counts and chat_ids,so a dashboard is configuration, not refactoring: fallback and ungrounded rates per day, latency charts, an alert if grounding errors spike.


