"""Run ingestion for a user from the command line (handy for testing without
the browser POST). Uses the user's stored, encrypted credentials.

Usage:  python -m scripts.ingest_cli <user_email> [limit]
"""

from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from backend.adapters.db.repositories import EmailRepository, TaskRepository  # noqa: E402
from backend.adapters.db.token_store import get_token_store  # noqa: E402
from backend.adapters.gmail.client import GmailAdapter  # noqa: E402
from backend.adapters.google.oauth import GoogleOAuthService  # noqa: E402
from backend.config import get_settings  # noqa: E402
from backend.services.ingestion import IngestionService  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.ingest_cli <user_email> [limit]")
        return 1
    user_id = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    settings = get_settings()
    oauth = GoogleOAuthService(settings, get_token_store())
    creds = oauth.load_credentials(user_id)
    if creds is None:
        print(f"No stored credentials for {user_id}. Log in first at /auth/login.")
        return 1

    gmail = GmailAdapter(creds)
    print(f"Ingesting up to {limit} emails for {user_id} ...")
    result = IngestionService().ingest_for_user(user_id, gmail, limit=limit)
    print("Result:", result)

    print("\n--- Triaged emails ---")
    for e in EmailRepository().list_for_user(user_id, limit=limit, order_by_priority=True):
        print(f"[{e.priority:>3}] {e.category:<12} {(e.subject or '')[:50]!r}")
        print(f"      {e.summary_one_line}")

    tasks = TaskRepository().list_for_user(user_id)
    print(f"\n--- Tasks ({len(tasks)}) ---")
    for t in tasks:
        print(f"  - {t.description}  (due {t.due_date})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
