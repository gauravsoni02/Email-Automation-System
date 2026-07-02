<div align="center">

# 📬 Aegis Mail AI

**A human-in-the-loop inbox & calendar assistant that never sends anything without your say-so.**

Aegis reads your Gmail, triages what actually needs attention, drafts replies, proposes meeting times against your calendar, and answers questions grounded in your own mail — but every irreversible action stops at an approval gate you control.

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/Streamlit-UI-FF4B4B?logo=streamlit&logoColor=white">
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-agents-1C3C3C">
  <img alt="Postgres" src="https://img.shields.io/badge/Postgres-pgvector-4169E1?logo=postgresql&logoColor=white">
  <img alt="Status" src="https://img.shields.io/badge/status-MVP%20complete-brightgreen">
</p>

</div>

---

## Table of contents

- [Why Aegis](#why-aegis)
- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Security model](#security-model)
- [Project structure](#project-structure)
- [Evaluation](#evaluation)
- [Known limitations](#known-limitations)
- [License](#license)

---

## Why Aegis

Most "AI email" tools ask you to trust an agent with your outbox. Aegis is built on the opposite premise: **the assistant does the reading, thinking, and drafting — you keep the send button.**

The flagship guarantee: **no email is ever sent, and no irreversible action is ever taken, without an explicit, authenticated human approval.** This isn't a setting you can flip off — it's enforced structurally in the agent graph itself (see [Security model](#security-model)).

---

## Features

| Capability | What it does |
|---|---|
| 🔐 **Google sign-in** | OAuth 2.0 with PKCE and CSRF-bound `state`; tokens encrypted at rest. |
| 📥 **Ingestion pipeline** | `fetch → store → embed → process` over your Gmail, into Postgres. |
| 🏷️ **Automatic triage** | Every email is classified, prioritized (0–100), summarized, and mined for action items. |
| 🔎 **Hybrid search** | One SQL query blending semantic (pgvector) + keyword (tsvector) + metadata filters; degrades gracefully to keyword-only. |
| ✍️ **Reply & scheduling agent** | A LangGraph agent that reads a thread, checks your calendar for scheduling requests, proposes times, and drafts a reply. |
| ✅ **Human-in-the-loop approval** | The agent **interrupts before sending**. You review, edit, approve, or reject. Nothing sends autonomously. |
| 💬 **Grounded chat** | Ask questions about your inbox; answers are cited from your own emails, with conversation memory. |
| 🔔 **Follow-ups & daily digest** | A background scan drafts nudges for stale, important, unanswered mail; a digest rolls up priorities, pending replies, meetings, and tasks. |
| 🧪 **Evals & hardening** | A triage eval harness plus rate limiting, step budgets, input validation, and encrypted secrets. |

---

## How it works

```
                    ┌─────────────────────────────────────────────┐
                    │                Streamlit UI                 │
                    │   (thin client — HTTP only, no logic)       │
                    └───────────────────────┬─────────────────────┘
                                            │ HTTP
                    ┌───────────────────────▼─────────────────────┐
                    │                 FastAPI backend             │
                    │                                             │
   Gmail/Calendar ──┤  adapters ── services ── LangGraph agents   │
   (read-only)      │      │           │            │             │
                    │      │        SearchService   │ interrupt() │
                    │      ▼           │            ▼             │
                    │  triage ──►  Postgres + pgvector  ◄── checkpointer
                    │  (classify/       (emails, tasks,          │
                    │   prioritize/      action_queue)           │
                    │   summarize/                               │
                    │   extract_tasks)         ▲                 │
                    └──────────────────────────┼─────────────────┘
                                               │
                                     ✋ Approval gate
                              (the ONLY path that sends mail)
```

Key design choices:

- **Everything sits behind seams** — `LLMClient`, `EmbeddingClient`, `TokenStore`, and `SearchService` are interfaces, so providers and storage can be swapped without touching business logic.
- **Tools are deterministic graph nodes, not LLM tool-calls.** Calendar free/busy lookups happen in fixed nodes, which contains prompt-injection risk from untrusted email content.
- **State is checkpointed to Postgres**, so an approval can resume an interrupted agent across separate requests or even server restarts.

---

## Tech stack

| Layer | Choice |
|---|---|
| **Frontend** | Streamlit (thin UI, HTTP only) |
| **Backend** | FastAPI |
| **LLM** | Any OpenAI-compatible provider (default **GroqCloud**), behind `LLMClient` |
| **Embeddings** | OpenAI-compatible (default **Google Gemini** free tier), behind `EmbeddingClient` |
| **Database** | Postgres + **pgvector** (hosted — Neon / Supabase; no Docker required) |
| **Agents** | **LangGraph** (reply/scheduling + chat) |
| **Scheduler** | APScheduler (no Redis/Temporal) |

---

## Quickstart

### Prerequisites

- Python 3.11+
- A hosted Postgres database with the `pgvector` extension available (e.g. [Neon](https://neon.tech) or [Supabase](https://supabase.com))
- A GroqCloud API key — [console.groq.com](https://console.groq.com)
- An embeddings API key (Google Gemini free tier works)
- A Google Cloud project with the **Gmail API** and **Calendar API** enabled

### 1. Install

```bash
# clone
git clone https://github.com/gauravsoni02/Email-Automation-System.git
cd Email-Automation-System

# virtualenv (recommended)
python -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows PowerShell

pip install -r requirements.txt
```

### 2. Configure Google OAuth

1. In the [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API** and **Google Calendar API**.
2. Configure the OAuth consent screen (**External**; add yourself as a test user).
3. Create an **OAuth client ID** of type *Web application* with redirect URI:
   ```
   http://localhost:8000/auth/callback
   ```

### 3. Set environment variables

```bash
cp .env.example .env               # macOS/Linux  (copy .env.example .env on Windows)
```

Then fill in `.env` (see [Configuration](#configuration)). To generate the token-encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4. Initialize the database

```bash
python -m backend.db.migrate       # creates the vector extension + tables
```

### 5. Run it

```bash
# Terminal 1 — backend
uvicorn backend.main:app --reload

# Terminal 2 — frontend
streamlit run frontend/app.py      # → http://localhost:8501
```

Then, in the Streamlit app: **Sign in with Google → Ingest & triage now →** explore the *Needs attention*, *Inbox*, *Search*, *Chat*, *Pending*, and *Digest* tabs.

---

## Configuration

All configuration is environment-driven (`backend/config.py`). Core variables:

| Variable | Required | Description |
|---|:---:|---|
| `LLM_API_KEY` | ✅ | API key for your OpenAI-compatible LLM provider (GroqCloud by default). |
| `EMBEDDING_API_KEY` | ✅ | API key for the embeddings provider. |
| `DATABASE_URL` | ✅ | Postgres connection string (with pgvector). Also switches `TokenStore` to Postgres-backed. |
| `GOOGLE_CLIENT_ID` | ✅ | OAuth client ID. |
| `GOOGLE_CLIENT_SECRET` | ✅ | OAuth client secret. |
| `TOKEN_ENCRYPTION_KEY` | ✅ | Fernet key used to encrypt OAuth tokens at rest. |
| `SESSION_TTL_SECONDS` | — | Session lifetime (default 7 days). |
| `ENABLE_SCHEDULER` | — | Set `true` to run the daily follow-up/digest job in the background. |

> LLM and embedding **model names** also live in `backend/config.py`, so you can point them at any OpenAI-compatible model without code changes.

---

## API reference

The Streamlit UI is a thin client over these endpoints — all business logic lives in the backend.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET`  | `/health` | Liveness + whether LLM/DB/OAuth are configured. |
| `GET`  | `/auth/login` · `/auth/callback` · `/auth/whoami` | OAuth flow and current account. |
| `GET`  | `/emails?limit=` | Recent inbox emails. |
| `GET`  | `/events/today` | Today's calendar events. |
| `POST` | `/ingest` · `/ingest/sync?limit=` | Run the fetch → store → embed → process pipeline. |
| `GET`  | `/triaged` · `/tasks` | Triaged emails (category/priority/summary) and extracted tasks. |
| `GET`  | `/search?q=&category=&sender=&unread_only=` | Hybrid semantic + keyword search. |
| `POST` | `/agent/reply` | Draft a reply/scheduling response → queued as **pending**. |
| `GET`  | `/actions` | List pending actions. |
| `POST` | `/actions/{id}/approve` | Approve (optionally edit subject/body) → the **only** path that sends mail. |
| `POST` | `/actions/{id}/reject` | Discard a pending draft. |
| `POST` | `/chat` | Grounded, cited Q&A over your inbox (pass `conversation_id` for memory). |
| `POST` | `/followup/scan?days=&min_priority=` | Draft follow-up nudges for stale, important, unanswered mail. |
| `GET`  | `/digest` | Top priorities, pending replies, upcoming meetings, and due tasks. |

All read/write endpoints require a valid session — unauthenticated requests return **401**.

---

## Security model

Aegis was reviewed against a code + security audit. The core guarantees:

- **Autonomous-action boundary.** `GmailAdapter.send_message` is reachable *only* from the reply graph's `send` node, which sits downstream of a LangGraph `interrupt()`. There is no code path that sends mail without an explicit, authenticated approval. Approve/reject transition the queued action **atomically** (`claim_pending`), so concurrent approvals can't double-send.
- **Auth.** OAuth uses **PKCE**; the `state` parameter is validated server-side *and* bound to the initiating browser via a cookie (login-CSRF protection). Session tokens are Fernet-encrypted, `HttpOnly`, and expire (`SESSION_TTL_SECONDS`).
- **Isolation & injection containment.** Every DB query is parameterized and scoped to the authenticated `user_id`. Email content is treated as **untrusted data** — agents use deterministic tool nodes rather than hijackable LLM tool-calling, and email headers are sanitized before send.

---

## Project structure

```
backend/
  main.py            FastAPI entry point
  config.py          env-driven settings (LLM/embedding model names live here)
  routers/           health, auth, emails, digest, actions, chat, search
  services/          domain logic + SearchService seam
  adapters/
    llm/             LLMClient interface + OpenAI-compatible adapter + factory
    gmail/ calendar/ db/   Gmail, Calendar, and Postgres adapters
  agents/            LangGraph graphs (reply/scheduling + chat)
  db/migrate.py      schema + pgvector setup
frontend/
  app.py             Streamlit thin UI
evals/
  run_evals.py       triage eval harness
  fixtures/          hand-labelled fixture emails
scripts/
  test_llm.py        LLM acceptance check
  verify_setup.py    verifies token encryption at rest
```

---

## Evaluation

```bash
python -m evals.run_evals          # prints triage scores
```

The harness runs the triage processors over hand-labelled fixture emails (`evals/fixtures/emails.json`) and reports:

- **Classification accuracy** — predicted category vs. expected label.
- **Task-extraction recall** — fraction of task-bearing emails where at least one task was extracted.
- **Priority separation** — average priority of important categories (urgent/finance/meeting/work) vs. low-value ones (promotion/newsletter/notification); the former should score higher.

**Hardening in place:** agents run under a `recursion_limit` step budget; expensive endpoints (`/chat`, `/agent/reply`, `/followup/scan`, `/ingest`, `/search`) are rate-limited per user; all inputs are validated with pydantic; OAuth tokens are Fernet-encrypted at rest (verify with `python -m scripts.verify_setup`).

---

## Known limitations

These are deliberate MVP tradeoffs, not oversights:

- The session token is passed to the Streamlit UI via a URL query param (the API and UI are separate origins). Fine for localhost; a production build would use a shared-domain cookie or a one-time exchange code.
- Rate-limit / OAuth-state / active-model state are in-memory (single-process). Move these to Postgres-backed stores before running multiple workers.
- The runtime model switch is process-global, not per-user.

---

## License

This project is licensed under the MIT License. See the root [LICENSE](LICENSE) file for the full text.

---

<div align="center">
Built by Gaurav Soni · Issues and PRs welcome.

<p>
  <a href="https://github.com/gauravsoni02">
    <img alt="GitHub" src="https://img.shields.io/badge/GitHub-gauravsoni02-181717?logo=github&logoColor=white">
  </a>
  <a href="https://www.linkedin.com/in/gauravsoni02/">
    <img alt="LinkedIn" src="https://img.shields.io/badge/LinkedIn-Gaurav%20Soni-0A66C2?logo=linkedin&logoColor=white">
  </a>
</p>
</div>
