# Cadre Support Bot: Playbook
We are building a support chatbot for Cadre (AI strategy and implementation consultancy) from scratch
Stack: FastAPI + React (Vite) + Claude API. Answers come from a curated KB injected into the system prompt. No RAG, no db in v1
WEBSITE URL: https://www.cadreai.com/
BOOKING: https://www.cadreai.com/contact

## Goal
A deployed public chatbot that answers Cadre's common inbound questions from the KB and hands off to a human (booking link) when it can't

## Commands
- API: `uvicorn app.main:app --reload --port 8000`
- UI: `cd frontend; npm run dev` (proxies /api) · build: `npm run build`
- Tests: `pytest -q`

## Layers (high overview architectur, this is what we build)

1. UI (frontend/src)
   - Gate.jsx: one screen asking for the access code before the chat shows. the code goes to sessionStorage and api.js sends it as the X-Access-Code header on every call; a 401 sends the user back to the gate
   - App.jsx: the chat page: messages, input, loading, error banner, fallback card with the booking link 
   - api.js: all fetch calls live here, components never call the backend directly
   - RULE: the UI only knows the JSON contract, not the model or the KB
2. API (app/api)
   - schemas.py: ChatRequest{message}, ChatResponse{chat_id, reply, fallback or null}
   - routes: POST /api/v1/chat, POST /api/v1/chat/{id}/messages, GET /api/v1/chat/{id}, GET /health
   - POST /api/v1/chat/{id}/contact {name, email}: stores the contact from the fallback card on the session + logs it
   - every /api/v1/* route except /health requires the X-Access-Code header to match ACCESS_CODE (layer 6). wrong or missing: 401 ACCESS_DENIED
   - trim to the last 10 messages before calling core
   - only validates and maps errors (bad access code:401, AI down:502, rate limit:429, bad chat id:404 UNKNOWN_CHAT). no logic here
3. Core (app/core)
   - prompt_builder.py: build_system_prompt(sections): persona + sections + boundaries + fallback protocol. never imports app/data, sections come from the caller
   - ai_service.py: the ONLY file that talks to the LLM, through API_KEY (.env file) the model is whatever LLM_MODEL says, any provider.
   Should: 
   - Use openai package (standard) official OpenAI Python SDK, pointed at BASE_URL from the env. provider agnostic on purpose: the key, the endpoint and the model are all env vars, we only know the key is for the LLM calls
   - Have functions to: get_response(messages) and reply, pull out the fallback. Control AIUnavailableError / AIRateLimitError (mapped from the
     SDK's APIStatusError / RateLimitError)
   - Run a grounding check on every non fallback answer: a second LLM call gets the answer + the KB sections and returns GROUNDED or UNGROUNDED. ungrounded, or the check itself errored: don't ship the generated answer, reply with the matching KB section text verbatim (simple keyword match on section titles; no match: the fallback card) and log it. verbatim KB text can't hallucinate.
   - cap replies at ~500 output tokens: support answers are short, and it bounds the cost of every message
   - MOCK_LLM=true (dev only): get_response and the grounding check return canned replies without touching the network, so building and clicking through the UI costs zero credits. never on in Render
4. Knowledge (app/data)
   - the KB content lives in docs/cadre-kb.md (markdown bc it's the standard) for v1.
   - content is curated from Cadre's public website at BUILD time, each section notes its source URL, refreshing means revisit the page, update the
     section. the bot never fetches the site at runtime.
   - what goes in the KB: the evergreen core (home, about, the services, industries/departments as one-liners + link, booking) never paraphrase, extract full information,
   - NOT in the KB: articles, case studies, podcast, events, unbounded content the future RAG use (not in v1)
   - some information will be there as manually sourced info, dont delete this or update
   - knowledge.py: loads that file at startup, parses each section heading into KnowledgeSection(id, title, content). fails fast if the file is missing or a section is empty
   - repository.py: KnowledgeSource.retrieve(query) that go to sections. static impl returns everything and ignores the query, the param exists so RAG can drop in later without touching callers. also get_booking_link()
5. Sessions (app/sessions)
   - three pieces: Message/Session models, a SessionStore interface (python  ABC, must implement: create/get/save/delete), and a SessionManager on top
   - v1 store is in-memory: a dict with a lock and a TTL check on read. redis replaces it later behind the same interface, callers unchanged
   - routes only ever talk to SessionManager, get_session returning None means expired/unknown, that's the 404. writes only through save()
   - the store keeps the full history; trimming to the last 10 for the model is the route's job, not the store's
6. Config (app/config.py)
   - pydantic-settings: API_KEY, BASE_URL (the endpoint the key belongs to), llm_model (as provided from the API key), ACCESS_CODE (the gate code), MOCK_LLM (default false), session ttl (3600), environment, log level
   - nothing else reads os.environ
7. Deploy (GitHub + Dockerfile + Render)
   - GitHub only stores the code, it doesn't run it. Render is the server: it watches the GitHub repo, builds the Dockerfile, and serves the app on
     a public URL (https://<app-name>.onrender.com)
   - one-time setup, done in the dashboard not in code: render.com > New > Web Service > connect the GitHub repo > runtime: Docker > add the env
     vars (API_KEY, BASE_URL, LLM_MODEL, ACCESS_CODE) > create. from then on every push to main auto-rebuilds and redeploys, no manual step
   - one Dockerfile, two stages: a node stage builds the React app into static files, then a python stage copies them in and runs uvicorn, so the final image ships without node
   - Render runs the container and tells it which port to use through $PORT, the app listens on that, never a hardcoded port
   - secrets (the API key) live only in Render's env vars, never in the repo

Flow: 1 > 2 > 5 load > 4 retrieve > 3 prompt + LLM + grounding check > 5 save > back up>
Cross layers only through these interfaces, anything else, stop and ask>

## Rules (build requirements)
- when the LLM call fails, ai_service raises its typed errors and layer 2 maps them to HTTP codes (details in layers 3+2). never catch the error and return the text as if the bot answered
- every error the API returns has the same shape: {"code": "UNKNOWN_CHAT", "message": "human readable text"}. the code is ALL_CAPS_WITH_UNDERSCORES and never changes bc the UI switches on it; the message can be reworded freely
- session writes only happen through SessionManager.save(), nothing outside the manager touches the store (the layer 5 rule that makes the redis swap possible)
- logging with structlog only: logger.info("event", key=value). never log the API key or the full system prompt
- shared objects (settings, ai service, session manager) live behind get_*() functions so there's exactly one of each. nothing runs at import time except create_app()
- only repository.py imports knowledge.py. changing KB content and changing bot behavior are different jobs, separate commits
- keep files under ~300 lines. if one is about to cross, propose a split first
- no answer ships unchecked: every non-fallback reply passes the grounding check before the route returns it (mechanism + degraded path: layer 3). every catch is logged so we can measure how often the model tried to invent

## Testing (how we verify, two kinds, don't mix them)
1. pytest (tests/): plain-function tests that run offline on every change. never call the network, the LLM client gets replaced with a fake that
   returns canned replies (one normal answer, one with the <fallback/> marker, one ungrounded case). cover: the assembled prompt actually contains the KB  + boundaries, the marker parser, the grounding verdict parser, the KB section matcher, session TTL expiry, error code mapping, the access code gate (401 without the header). routes are tested with FastAPI's TestClient (no server needed), asserting status codes and the {code, message} error shape
2. /verify-scenarios: the end-to-end check against the RUNNING app with the real LLM. it walks the 6 brief scenarios (the exact list lives in .claude/skills/verify-scenarios) and fails any answer that invents facts not in the KB. run it locally at the end of each phase, and once against the DEPLOYED url before calling the project done
- structure: tests/ mirrors app/ (test_prompt_builder.py, test_ai_service.py, test_sessions.py, test_api.py). one behavior per test, the name says what it proves
- a failing test means the code or the assumption is wrong, fix that

## Scope V1
In:
1. QA over the KB
2. multiturn sessions, last 10 messages to the model
3. fallback with booking link + optional name/email capture
4. minimal React chat UI served by FastAPI, so it's one deploy
5. one-screen access-code gate: the deployed bot spends real credits per message, the gate keeps strangers from draining them

Out, on purpose:
1. RAG / vector db: nothing to retrieve at this size, it only adds latency and failure modes. the seam is ready (layer 4), adding it later = one new class
2. redis: single instance demo, interface ready in layer 5
3. real auth (accounts, JWT): overkill for a demo bot
5. dashboards / analytics / CRM: with more time
6. runtime site crawling: the KB holds only the stable evergreen core and already excludes the fast-changing content (what goes in/out: layer 4).
   when that content needs to come in, the crawl becomes the ingestion step of the RAG impl (crawl > chunk > embed > the layer 4 seam) on v2

## Decisions already made (apply them, don't reconsider)
1. LLM through API_KEY with the openai SDK + base_url. model: env var, default a Claude haiku-tier model if possible, upgrading later or A/B-ing ANY provider's model means flip one env var
2. when the bot can't answer, the model writes a small marker inside its reply: <fallback reason=""/>. ai_service finds it, strips it out, and the
   API returns the fallback card instead. we chose this over tool calling bc it's the same behavior with fewer moving parts, and the parser is a plain function we can test without touching the network
3. the prompt is assembled from two files that never mix: behavior rules live in prompt_builder (layer 3), the facts live in the KB (layer 4). editing what the bot KNOWS never risks changing how it BEHAVES, and vice versa
4. tests live where AI-generated code lies the most, run offline with a faked LLM client. the full list of what to cover and how: the Testing section
5. the KB comes from Cadre's real website, not just the brief, so answers are real and every fact traceable to its source URL (curation rules: layer 4). not in the KB = the bot falls back, never guesses
6. we don't just ask the model to be honest, we check it: the prompt sets boundaries and gives the fallback way out (prevention), the grounding
   check verifies every answer before it ships and degrades to verbatim KB text that can't lie (detection, mechanism: layer 3), and
   /verify-scenarios re-tests the 6 scenarios end to end (Testing)

## Build order (the phases for plan.md)
1. skeleton live (layers 2+6+7): config, app factory that fails fast if the API key is missing, /health, static mount, Dockerfile, deployed to Render, BEFORE any AI code
2. core chat (4+3+5, then 2+1): KB + repository > prompt_builder > ai_service > sessions > routes > UI
3. fallback + grounding check + polish (1+2+3): grounding check wired into ai_service, contact capture, error states, README
4. verify (all): pytest + the 6 brief scenarios on the DEPLOYED URL, update known issues

## Workflow Orchestration

### 1. Plan Default
- Everything comes from plan.md once generated. Don't add features, endpoints, or deps not in it, ask first
- Enter plan mode for any non trivial change (3+ steps or touching 2+ layers)
- If a task goes sideways, STOP and replan don't keep pushing

### 2. Subagent Strategy
- Offload research, exploration, and independent tasks to subagents to keep the main context clean. One task per subagent, scoped by layer
- reviewer subagent after each phase; /verify-scenarios for the end-to-end check

### 3. Self Improvement Loop
- After ANY correction: add one line to Rules above so it doesn't repeat
- Review Rules at session start

### 4. Verification Before Done
- Never mark done without proof: pytest passes + curl the endpoint (or click the UI) and show the REAL output
- Say what you changed and what you're unsure about

### 5. Elegance
- Before writing a new helper, abstraction, or dependency: check whether a layer interface or something already built in this repo covers it
- If a fix needed a workaround (sleep, retry loop, broad except, hardcoded value): stop and redo it clean now that the cause is known
- Don't over-engineer: the ONLY planned growth seams are the layer 4/5/6 interfaces,don't invent additional abstractions for futures not in planmd.

### 6. Autonomous Bug Fixing
- Given an error, log, or failing test: just fix it, reproduce, find the root cause, verify. No temporary patches, no suppressed errors

## Task Management
1. plan.md is the task list: mark its phase checkboxes complete as you go, one-line summary per step
2. Endpoint added or changed > update the README endpoint table in the same commit
3. Small commits, one verified step each

## Standards (what "good" means in this project)
- Follow the architecture: a change lives in ONE layer, and layers connect only through their interfaces (the flow rule under Layers)
- Build modular for growth: a new capability is a new implementation of a layer interface (the 4/5/6 seams), not edits to the callers
- Root cause over patch: a failing test means fix the code or the wrong assumption, never loosen the assertion, add a sleep, or catch-and-ignore
- Reuse before adding: check what this repo already has before writing a new helper. No dead code, no commented-out blocks, no unused parameters
- Secrets only through env/settings (layers 6+7): API_KEY never in code or commits, .env stays gitignored
