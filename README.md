# Resilient LLM Chatbot

A React + FastAPI chatbot that keeps working when an API key fails and answers repeated
requests from cache. LiteLLM handles provider calls and caching; SQLite stores history.

## Live URLs

- Frontend: _add after deployment_
- Backend: _add after deployment_ (health check at `/health`)

## Run locally

Copy `.env.example` to `.env` and set at least two keys in `LLM_API_KEYS`.

### With Docker

```bash
make up      # backend http://localhost:8000, frontend http://localhost:3000
make down
```

History lives in the `chat-data` volume at `/data/app.db` and survives restarts.

### Without Docker

Backend (Python 3.12+), PowerShell:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:DATABASE_URL="sqlite:///./app.db"
uvicorn app.main:app --port 8000 --env-file ../.env
```

On macOS or Linux, activate with `source .venv/bin/activate` and use `export`.
Variables already set in the shell take priority over `--env-file`.

Frontend (Node 20+), in a second terminal:

```bash
cd frontend
npm ci
npm run dev   # http://localhost:3000
```

Note: Vite cannot build from a folder whose path contains `#`.

Tests (no keys or network needed): `cd backend && python -m pytest`

### Environment variables

| Variable | Meaning |
|---|---|
| `LLM_API_KEYS` | Comma-separated pool, at least 2. Ids are `key_1`, `key_2`, ... in order |
| `LLM_MODEL` | LiteLLM model name; a comma-separated list rotates across keys |
| `DATABASE_URL` | e.g. `sqlite:////data/app.db` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | `true` enables the `X-Simulate-Failure` header |
| `DEFAULT_SYSTEM_PROMPT` | Prompt used when a session has none |
| `LLM_TIMEOUT_SECONDS` | Time limit per provider attempt (default 20) |
| `CACHE_TYPE`, `CACHE_DIR`, `CACHE_TTL_SECONDS` | `local` (in-memory) or `disk`; folder; lifetime |
| `VITE_API_URL` | Backend URL, built into the frontend |

## Design decisions

### Key fallback

- LiteLLM's `Router` holds one deployment per key. Router retries, SDK retries and cooldowns
  are off, so every request tries `key_1`, `key_2`, ... in order and moves on immediately.
- The order is controlled by a small loop in `backend/app/gateway.py` rather than Router's
  `fallbacks` setting. This gives an exact `key_id` and `fallback_attempts` for every reply,
  and lets a simulated failure target one key in one request.
- Any provider error moves to the next key: 429, quota, 5xx, and also timeouts, rejected keys
  and empty replies. If every key fails, the API returns `503 {"detail": "all providers unavailable"}`.
- `X-Simulate-Failure` makes LiteLLM raise the matching exception through `mock_response`, so
  simulated and real failures follow the same path.
- Logs contain only the key id, error type and status code, never keys or provider messages.
- Trade-off: without cooldowns, a key that stays broken costs one failed attempt per request.
  Predictable ordering mattered more at this scale.

### Caching

- Uses LiteLLM's built-in `Cache`. The key is built from the model and the full message list
  (system prompt, history, new message). The API key is not part of it, so a reply produced by
  one key is reused whichever key is first in line.
- Lookup and storage are explicit, so `LLM_CACHE` is reported only on a real cache hit.
- A hit returns the stored text and token usage, with `key_id: null` and `fallback_attempts: 0`.
- Simulated requests neither read nor write the cache. Otherwise a cached reply would hide the
  failover being tested.
- The default cache is in memory: it is per process and empties on restart.

### SQLite session storage

- `messages` follows the required model, indexed by `(session_id, id)`. A `sessions` table keeps
  each session's system prompt, which is never returned by the history endpoint.
- The question, answer and prompt are written in one transaction, only after a successful reply.
  A 422 or 503 leaves no trace.
- A per-session lock stops parallel messages in one chat from interleaving. This assumes a single
  backend process, which is how the container runs.
- The full history is sent on every turn. Very long chats would eventually need trimming.

### Hosting limitation

On Docker Compose, history persists in a named volume. A free hosting tier without a persistent
disk loses the SQLite file when the service restarts, redeploys or sleeps. For durable hosted
history, mount a persistent disk at `/data`. A sleeping service also makes the first request slow.

### Security

Keys come only from environment variables and are never returned to the client. CORS is limited
to configured origins, containers read config at run time, and the backend runs as a non-root user.
There is no authentication or rate limiting, and anyone who knows a session id can read it.
`ENABLE_FAILURE_SIMULATION` is on for evaluation; turn it off for real use.

## Verification

Check everything against a running backend (uses real keys, simulation must be enabled):

```bash
python scripts/smoke_test.py http://localhost:8000
```

PowerShell, with `$API` set to the backend URL:

```powershell
$API="http://localhost:8000"
$body='{"session_id":"demo-1","message":"What is the capital of France?"}'
Invoke-RestMethod "$API/health"

# Failover: the answer comes from key_2
Invoke-RestMethod "$API/chat" -Method Post -ContentType "application/json" -Headers @{"X-Simulate-Failure"="key_1=429"} -Body $body | ConvertTo-Json

# Every key fails: 503
Invoke-WebRequest "$API/chat" -Method Post -ContentType "application/json" -Headers @{"X-Simulate-Failure"="*=429"} -Body $body -UseBasicParsing

# Stored history
Invoke-RestMethod "$API/sessions/demo-1/messages" | ConvertTo-Json -Depth 5
```

- **Cache hit:** in the UI, send a message, click **New chat** (or reload) and send the same
  text. The second reply shows `LLM_CACHE`, identical text and a lower latency.
- **Token usage:** each reply shows input and output tokens for that request only. Input tokens
  grow within a chat because history is part of the prompt; they are not a running total.

The GitHub Actions workflow runs the tests, then `make up` with placeholder keys and checks
both services and the all-keys-fail response.

## Setup Used

- Editor and AI tools: Claude Code (Claude Sonnet 5.5) in the Claude desktop app, used to plan,
  write and test the code.

## Bonus features

- Optional system prompt field, remembered per session.
- A failover test menu that sends `X-Simulate-Failure` from the UI, so recovery can be seen
  without a terminal. Each reply shows which keys failed and which one answered.
- Markdown formatting for replies.
- **New chat** button, server status with a cold-start notice, and the failed message is put
  back in the input for a quick retry.
- The UI shows which key answered and how many failovers happened.
- CI that checks tests and `make up`, plus a contract smoke test for deployed backends.
