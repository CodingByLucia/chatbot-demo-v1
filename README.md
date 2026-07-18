# Cadre Support Bot

A support chatbot for [Cadre](https://www.cadreai.com/), an AI strategy and implementation consultancy. It answers common inbound questions from a curated knowledge base and hands off to a human (booking link + optional contact form) when it can't.

**Stack:** FastAPI + React (Vite) + any OpenAI-compatible LLM endpoint. The built frontend is served by FastAPI, so it's a single deploy.

## How it works

- The knowledge base ([docs/cadre-kb.md](docs/cadre-kb.md)) is curated from Cadre's public website at build time and injected into the system prompt. The bot never fetches the site at runtime.
- When the model can't answer from the KB, it emits a `<fallback reason=""/>` marker; the API strips it and returns a fallback card with the booking link and an optional name/email form. The same card is also attached whenever the answer itself recommends a contact channel (an email address, a phone number, the contact page, or booking a call).
- Every non-fallback answer passes a grounding check: a second LLM call verifies the answer against the KB. If the answer is ungrounded (or the check fails), the bot ships the matching KB section verbatim instead — or the fallback card when no section matches.
- All `/api/v1/*` routes require an `X-Access-Code` header; a one-screen gate in the UI collects it. This keeps strangers from draining LLM credits on the public deploy.

## Run locally

Backend (Python 3.11+):

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use source .venv/bin/activate on mac/linux
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # fill in the values (see Configuration)
uvicorn app.main:app --reload --port 8000
```

Frontend (dev server proxies `/api` to port 8000):

```bash
cd frontend
npm install
npm run dev
```

For a combined run like production, build the UI once (`cd frontend; npm run build`) and FastAPI serves `frontend/dist` at `/`.

Set `MOCK_LLM=true` in `.env` to click through the whole UI with canned replies and zero LLM credits (a message containing "fallback" triggers the canned fallback card). Never enable it in production.

## Configuration

All settings come from environment variables (or `.env` locally). Nothing else reads the environment.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `API_KEY` | yes | — | Key for the LLM endpoint. Never committed; lives in `.env` / Render env vars |
| `BASE_URL` | yes | — | OpenAI-compatible endpoint the key belongs to |
| `LLM_MODEL` | yes | — | Model name the endpoint expects; swap providers/models by changing env only |
| `ACCESS_CODE` | yes | — | Code the UI gate asks for; sent as `X-Access-Code` on every API call |
| `MOCK_LLM` | no | `false` | Canned replies, no network calls (dev only) |
| `SESSION_TTL_SECONDS` | no | `3600` | Chat session expiry, refreshed on every save |
| `ENVIRONMENT` | no | `development` | `development` = pretty console logs, otherwise JSON |
| `LOG_LEVEL` | no | `INFO` | structlog filtering level |

## API

Every route under `/api/v1` requires the `X-Access-Code` header. Every error has the shape `{"code": "ALL_CAPS_CODE", "message": "human readable text"}` — the `code` is stable, the `message` can change.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check (no access code). Returns `{"status": "ok"}` |
| `GET` | `/api/v1/auth` | Access-code check used by the gate screen. Returns `{"status": "ok"}` when the `X-Access-Code` header is valid, 401 otherwise |
| `POST` | `/api/v1/chat` | Start a chat. Body `{"message"}` → `{"chat_id", "reply", "fallback"}` (`fallback` is `null` or `{"reason", "booking_url"}`) |
| `POST` | `/api/v1/chat/{chat_id}/messages` | Continue a chat. Same body and response as above |
| `GET` | `/api/v1/chat/{chat_id}` | Full history: `{"chat_id", "messages": [{"role", "content", "fallback"}]}` |
| `POST` | `/api/v1/chat/{chat_id}/contact` | Store the visitor's `{"name", "email"}` from the fallback card → `{"status": "ok"}` |

Error codes: `ACCESS_DENIED` (401), `UNKNOWN_CHAT` (404, unknown/expired chat), `INVALID_REQUEST` (422), `RATE_LIMITED` (429), `AI_UNAVAILABLE` (502), `NOT_FOUND` (404, unmatched path), `INTERNAL_ERROR` (500).

Only the last 10 messages of a session are sent to the model; the session store keeps the full history until the TTL expires.

## Testing

```bash
pytest -q
```

The suite runs fully offline: the LLM client is replaced with fakes, routes are exercised with FastAPI's `TestClient`. Covered: prompt assembly, the fallback-marker parser, the grounding verdict parser and KB section matcher, the ungrounded degrade path, session TTL expiry, the access gate, contact capture, and the error-code mapping.

## Deploy

One Dockerfile, two stages: node builds the React app, then the Python image copies the static files in and runs uvicorn on `$PORT`. Render watches the GitHub repo and rebuilds on every push to `main`; the env vars above (minus `MOCK_LLM`) are set in the Render dashboard, never in the repo.
