# Setup Guide — Aegis Mail AI

Step-by-step to install dependencies and run the app. See [README.md](README.md)
for the architecture and feature overview.

## 1. Prerequisites
- **Python 3.12+**
- A hosted **Postgres** with the **pgvector** extension (free tier at
  [Neon](https://neon.tech) or [Supabase](https://supabase.com))

## 2. Create a virtual environment & install requirements
From the project root:

```bash
# create + activate a virtualenv
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell/CMD)
# source .venv/bin/activate       # macOS / Linux

# install all dependencies
pip install -r requirements.txt
```

`requirements.txt` installs everything: FastAPI, Streamlit, the OpenAI SDK
(used for both the LLM and embeddings via OpenAI-compatible endpoints),
Google OAuth/API libraries, psycopg + pgvector, LangGraph (+ Postgres
checkpointer), and APScheduler.

## 3. Configure environment variables
Copy the template and fill it in:

```bash
copy .env.example .env          # Windows
# cp .env.example .env            # macOS / Linux
```

Fill these six values in `.env` (all have free options):

| Variable | Where to get it |
|---|---|
| `LLM_API_KEY` | [console.groq.com](https://console.groq.com) (free) — GroqCloud |
| `EMBEDDING_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (free) — Gemini |
| `TOKEN_ENCRYPTION_KEY` | generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GOOGLE_CLIENT_ID` | Google Cloud Console → OAuth client (Web app) |
| `GOOGLE_CLIENT_SECRET` | same OAuth client |
| `DATABASE_URL` | Neon/Supabase connection string (`postgresql://...?sslmode=require`) |

**Google OAuth setup:** create a Google Cloud project, enable the **Gmail API**
and **Google Calendar API**, configure the OAuth consent screen (External; add
your Gmail as a **test user**), and create an **OAuth client ID** of type
*Web application* with redirect URI `http://localhost:8000/auth/callback`.

## 4. Verify your setup (optional but recommended)
```bash
python -m scripts.verify_setup
```
Checks all keys are present and pings the LLM, embeddings, and database.

## 5. Initialize the database
```bash
python -m backend.db.migrate
```
Creates the pgvector extension, tables, and the LangGraph checkpointer tables.

## 6. Run the app
Two terminals (both with the virtualenv activated):

```bash
# terminal 1 — backend API
uvicorn backend.main:app --reload

# terminal 2 — frontend UI
streamlit run frontend/app.py
```

Open **http://localhost:8501**, click **Sign in with Google**, then use the
sidebar to **Ingest & triage** your inbox.

## 7. Run the evals (optional)
```bash
python -m evals.run_evals
```
Prints triage classification accuracy, task-extraction recall, and priority
separation over the fixture emails.

---

### Notes
- The LLM and embedding providers are chosen in `.env` and sit behind interfaces,
  so you can swap them without code changes (e.g. `LLM_BASE_URL`/`LLM_MODEL` for
  xAI or OpenAI). A model switcher is also available in the app sidebar.
- Free tiers have daily limits; if you hit a rate limit, wait for the reset or
  switch models/providers.
