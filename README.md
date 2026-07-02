# Aegis Mail AI

A personal inbox + calendar assistant. It reads your Gmail, triages what needs
attention, drafts replies, proposes meeting times against your calendar, and
**never takes an irreversible action without explicit human approval**. That
human-in-the-loop gate is the flagship feature.

See [CLAUDE.md](CLAUDE.md) for the full design, locked tech decisions, and the
phased build plan.

## Stack

- **Frontend:** Streamlit (thin UI, HTTP only)
- **Backend:** FastAPI
- **LLM:** OpenAI-compatible provider (default GroqCloud), behind an `LLMClient` interface
- **Embeddings:** OpenAI-compatible (default Google Gemini free tier), behind an `EmbeddingClient` interface
- **DB:** Postgres + pgvector (hosted — Neon/Supabase; no Docker)
- **Agents:** LangGraph (reply/scheduling + chat only)

## Status

**Phase 0 — Scaffolding & seams** ✅
Repo structure, env-driven config, the `LLMClient` seam (OpenAI-compatible,
default GroqCloud), the `SearchService` seam (stub), and a health endpoint.

**Phase 1 — Auth & read-only access** ✅
Google OAuth (login + callback with CSRF `state`), OAuth tokens encrypted at rest
(behind a `TokenStore` seam — encrypted-file now, Postgres in Phase 2), an
encrypted session cookie, and read-only Gmail (`list_emails`, `read_email`) and
Calendar (`list_events`, `get_free_busy`) adapters. No send/create paths exist.

**Phase 2 — Ingestion pipeline & triage processors** ✅
Postgres schema (users, emails, tasks, action_queue) with pgvector + tsvector;
`TokenStore` now Postgres-backed when `DATABASE_URL` is set. An `EmbeddingClient`
seam (OpenAI-compatible). Four stateless triage processors — classify, prioritize,
summarize, extract_tasks — as plain `LLMClient` JSON calls (not LangGraph). An
ingestion pipeline (fetch → store → embed → process) exposed at `POST /ingest`.

**Phase 3 — Hybrid search & first UI** ✅
`SearchService` implemented as one SQL query blending pgvector (semantic) +
tsvector (keyword) + metadata filters (category/sender/unread), behind the seam;
degrades to keyword-only when an email has no embedding. `GET /search`. A Streamlit
UI: Google sign-in, a ranked "needs your attention" digest, inbox, reading pane,
search, tasks, and an ingest button — all over HTTP, no business logic in the UI.

**Phase 4 — Reply / scheduling agent (LangGraph)** ✅
A real LangGraph graph: load_thread → route_intent → (scheduling? →
check_availability → propose_times) → draft_reply → enqueue. The model is bound
via the `LLMClient` seam; tools (calendar free/busy) are deterministic graph
nodes, not LLM tool-calls (prompt-injection containment). The terminal node writes
a **pending** `send_email` action to `action_queue` — no real send yet.
`POST /agent/reply`, `GET /actions`. UI: a "🤖 Draft reply" button + a Pending tab.

**Phase 5 — Human-in-the-loop approval** ✅
The graph now **interrupts before sending** (LangGraph `interrupt()`), persisting
state to a **Postgres checkpointer** so approval can resume it across requests /
restarts. `POST /actions/{id}/approve` (optional subject/body edits) resumes the
graph → the **executor** (`send` node) performs the real Gmail send — the only
code path that sends mail, only on explicit authenticated approval.
`POST /actions/{id}/reject` discards via the graph's discard path. Streamlit
review queue: edit, approve & send, or reject. Nothing sends autonomously.

**Phase 6 — Chat assistant (LangGraph)** ✅
The second real agent: retrieve (via the `SearchService` seam) → synthesize a
grounded, cited answer. Conversation memory via the Postgres checkpointer keyed on
a `conversation_id`. Emails are treated as untrusted (no instruction-following).
`POST /chat`. UI: a Chat tab. (Full-text index includes the sender, and keyword
search uses OR semantics, so "what did X ask me?" retrieves X's emails.)

**Phase 7 — Follow-up & daily digest (scheduler)** ✅
An APScheduler background job (no Redis/Temporal) runs a daily **follow-up scan**:
stale, high-priority, unanswered emails are routed through the reply agent to
produce **pending** follow-up drafts (reviewed via the same approval gate — never
auto-sent). A **digest** (`GET /digest`) assembles top priorities, pending
replies, upcoming meetings, and tasks due. `POST /followup/scan` triggers on
demand. UI: a Digest tab + a follow-up scan button.

**Phase 8 — Evals & hardening** ✅
`evals/run_evals.py` scores triage against fixture emails (classification
accuracy, task-extraction recall, priority separation) and prints numbers.
Hardening: LLM/embedding retries, an agent **step budget** (`recursion_limit`),
in-memory **rate limiting** on expensive endpoints, pydantic input validation,
structured logging, and verified token encryption at rest.

## Setup

```bash
# 1. (recommended) create a virtualenv
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
# source .venv/bin/activate    # macOS/Linux

# 2. install Phase 0 dependencies
pip install -r requirements.txt

# 3. configure
copy .env.example .env         # Windows
# cp .env.example .env          # macOS/Linux
# then edit .env and set LLM_API_KEY (GroqCloud key from console.groq.com)
```

## Run

```bash
# Backend (FastAPI)
uvicorn backend.main:app --reload

# Frontend (Streamlit), in a second terminal
streamlit run frontend/app.py
```

## Verify Phase 0 acceptance

1. **App boots + health endpoint responds:**
   ```bash
   uvicorn backend.main:app --reload
   # then:
   curl http://localhost:8000/health
   ```
   Expect `{"status": "ok", ...}` including whether the LLM/DB/OAuth are configured.

2. **A scripted `LLMClient` call returns a completion:**
   ```bash
   python -m scripts.test_llm
   ```
   With a valid `LLM_API_KEY`, this prints the model's text reply and a structured
   JSON reply (the path the triage processors will use).

## Phase 1 setup (Google OAuth)

1. In [Google Cloud Console](https://console.cloud.google.com/): create a project,
   enable the **Gmail API** and **Google Calendar API**, configure the OAuth
   consent screen (External; add yourself as a test user), and create an
   **OAuth client ID** of type *Web application* with redirect URI
   `http://localhost:8000/auth/callback`.
2. Put the client id/secret in `.env` (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`).
3. Generate a token-encryption key and add it to `.env`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   # -> TOKEN_ENCRYPTION_KEY=...
   ```

### Verify Phase 1 acceptance

```bash
uvicorn backend.main:app --reload
```
1. Open `http://localhost:8000/auth/login` in a browser → complete Google consent.
   You'll be redirected back and see `{"status":"authenticated",...}`; a session
   cookie is set and encrypted tokens are written to `.aegis_tokens.json`.
2. With that session cookie, these return JSON:
   - `GET http://localhost:8000/emails?limit=10` → your last 10 inbox emails
   - `GET http://localhost:8000/events/today` → today's calendar events
   - `GET http://localhost:8000/auth/whoami` → your account email

All read-only endpoints return **401** without a valid session.

## Phase 2 setup & verify (ingestion + triage)

Requires `DATABASE_URL` (hosted Postgres w/ pgvector) and `EMBEDDING_API_KEY`.

```bash
# 1. apply the schema (creates the vector extension + tables)
python -m backend.db.migrate

# 2. with an authenticated session (Phase 1), run ingestion synchronously:
#    POST http://localhost:8000/ingest/sync?limit=5
#    -> {"fetched": N, "processed": N, "failed": 0}

# 3. verify each email got triaged:
#    GET http://localhost:8000/triaged     -> emails with category/priority/summary
#    GET http://localhost:8000/tasks       -> extracted action items
```

Acceptance: after ingestion, every email row has a category, priority (0–100),
summary, an embedding, and any extracted tasks.

## Phase 3 — hybrid search & UI

Start both servers, then use the Streamlit app end-to-end:

```bash
uvicorn backend.main:app --reload          # terminal 1
streamlit run frontend/app.py              # terminal 2  -> http://localhost:8501
```

1. In the Streamlit app click **Sign in with Google** → after consent you're
   redirected back authenticated.
2. Sidebar → **Ingest & triage now**.
3. Browse the **Needs attention** digest / **Inbox** / **Tasks** tabs.
4. **Search** tab: natural-language queries (e.g. "project setup") plus optional
   category / sender / unread filters.

Search API directly: `GET /search?q=...&category=...&sender=...&unread_only=...`
Acceptance: natural-language + filtered queries return sensibly-ranked results.

## Phase 4 — reply / scheduling agent

In the Streamlit app, expand any email → **🤖 Draft reply**. The agent reads the
thread, decides if it's a scheduling request (and if so checks your calendar and
proposes times), drafts a reply, and queues it as a **pending** action. Review it
in the **Pending** tab. Nothing is sent.

API: `POST /agent/reply {"email_id": "...", "instruction": "..."}` → the pending
action; `GET /actions` → all pending actions.
Acceptance: replying to a scheduling email yields a pending draft with proposed
times, visible in the DB/UI; no email is sent.

## Phase 5 — human-in-the-loop approval

In the **Pending** tab, each draft is editable. Choose:
- **✅ Approve & send** — resumes the agent graph; the executor sends the (edited)
  email via Gmail. This is the only path that ever sends mail.
- **🗑️ Reject** — discards the draft; nothing is sent.

APIs: `POST /actions/{id}/approve {"subject","body"}`, `POST /actions/{id}/reject`.
Acceptance: a draft only sends after explicit approval; edits change the sent
content; reject discards it; nothing sends autonomously. (Graph state is persisted
by a Postgres LangGraph checkpointer, so approval works even across restarts.)

## Phase 6 — chat assistant

Chat tab, or `POST /chat {"message": "...", "conversation_id": "..."}`. Answers are
grounded in your emails and cite them; pass the returned `conversation_id` back for
follow-up questions (memory).

## Phase 7 — follow-up & digest

- `POST /followup/scan?days=3&min_priority=50` (or the sidebar button) drafts
  follow-up nudges for stale, unanswered, important emails — as **pending** actions.
- `GET /digest` returns top priorities, pending replies, upcoming meetings, tasks.
- Set `ENABLE_SCHEDULER=true` in `.env` to run these daily in the background.

## Phase 8 — evals & hardening

```bash
python -m evals.run_evals        # prints triage scores
```

### How I measured it
The eval harness runs the triage processors over 8 hand-labelled fixture emails
(`evals/fixtures/emails.json`) spanning the category set, and reports:
- **Classification accuracy** — predicted category vs. expected label.
- **Task-extraction recall** — fraction of task-bearing emails where ≥1 task was
  extracted.
- **Priority separation** — average priority of important categories
  (urgent/finance/meeting/work) vs. low-value ones (promotion/newsletter/
  notification); we expect the former to score higher.

Hardening in place: agents run under a `recursion_limit` step budget; expensive
endpoints (`/chat`, `/agent/reply`, `/followup/scan`, `/ingest`, `/search`) are
rate-limited per user; all inputs are validated with pydantic; OAuth tokens are
Fernet-encrypted at rest (verify with `python -m scripts.verify_setup`).

## Security notes

Reviewed against a code + security audit; key measures:
- **Autonomous-action boundary:** `GmailAdapter.send_message` is reachable only
  from the reply graph's `send` node, downstream of a LangGraph `interrupt()`.
  No path sends mail without an explicit, authenticated approval. Approve/reject
  transition the queued action **atomically** (`claim_pending`), so concurrent
  approvals can't double-send.
- **Auth:** OAuth uses PKCE; `state` is validated server-side **and** bound to the
  initiating browser via a cookie (login-CSRF protection). Session tokens are
  Fernet-encrypted, `HttpOnly`, and **expire** (`SESSION_TTL_SECONDS`, 7 days).
- **Isolation & injection:** every DB query is parameterized and scoped to the
  authenticated `user_id`; email content is treated as untrusted data (agents use
  deterministic tool nodes, not hijackable LLM tool-calling); email headers are
  sanitized before send.

### Known limitations (MVP tradeoffs)
- The session token is handed to the Streamlit UI via a URL query param (the API
  and UI are separate origins). Fine for localhost; a production build would use a
  shared-domain cookie or a one-time exchange code.
- Rate-limit / OAuth-state / active-model state are in-memory (single-process).
  Move to Postgres-backed stores before running multiple workers.
- The runtime model switch is process-global (not per-user).

## Layout

```
backend/
  main.py            FastAPI entry
  config.py          env-driven settings (LLM/embedding model names live here)
  routers/           health (auth/emails/digest/actions/chat/search come later)
  services/          domain logic + SearchService seam (stub)
  adapters/llm/      LLMClient interface + OpenAI-compatible adapter + factory
  adapters/gmail|calendar|db/   placeholders for later phases
  agents/            LangGraph graphs (Phase 4+)
frontend/app.py      Streamlit thin UI
scripts/test_llm.py  Phase 0 LLM acceptance check
evals/               eval harness (Phase 8)
```
