"""Preflight check: confirm every configured service actually responds.

Run from repo root:  python -m scripts.verify_setup
Checks presence of each .env value, then makes a real call to the LLM, the
embeddings provider, and the database. Prints PASS/FAIL per item; never prints
secret values.
"""

from __future__ import annotations

import sys

# Windows consoles default to cp1252; emit UTF-8 so status glyphs don't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from backend.config import get_settings  # noqa: E402


def _ok(label: str, detail: str = "") -> None:
    print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    settings = get_settings()
    failures = 0

    print("1) Config presence")
    required = {
        "LLM_API_KEY": settings.llm_api_key,
        "EMBEDDING_API_KEY": settings.embedding_api_key,
        "TOKEN_ENCRYPTION_KEY": settings.token_encryption_key,
        "GOOGLE_CLIENT_ID": settings.google_client_id,
        "GOOGLE_CLIENT_SECRET": settings.google_client_secret,
        "DATABASE_URL": settings.database_url,
    }
    for name, val in required.items():
        if val:
            _ok(name, "set")
        else:
            _fail(name, "missing")
            failures += 1

    print("\n2) Encryption key valid")
    try:
        from backend.security.crypto import get_crypto

        get_crypto.cache_clear()
        token = get_crypto().encrypt("ping")
        assert get_crypto().decrypt(token) == "ping"
        _ok("TOKEN_ENCRYPTION_KEY", "valid Fernet key, round-trip works")
    except Exception as exc:  # noqa: BLE001
        _fail("TOKEN_ENCRYPTION_KEY", f"{type(exc).__name__}: {exc}")
        failures += 1

    print("\n3) LLM (chat completion)")
    try:
        from backend.adapters.llm import ChatMessage, get_llm_client

        reply = get_llm_client().complete(
            [ChatMessage(role="user", content="Reply with the single word: pong")],
            max_tokens=8,
        )
        _ok("LLM", f"{settings.llm_model} replied: {reply!r}")
    except Exception as exc:  # noqa: BLE001
        _fail("LLM", f"{type(exc).__name__}: {exc}")
        failures += 1

    print("\n4) Embeddings")
    try:
        from backend.adapters.embeddings import get_embedding_client

        vec = get_embedding_client().embed("hello world")
        dim = len(vec)
        if dim == settings.embedding_dim:
            _ok("Embeddings", f"{settings.embedding_model} -> dim {dim} (matches EMBEDDING_DIM)")
        else:
            _fail(
                "Embeddings",
                f"dim {dim} != EMBEDDING_DIM {settings.embedding_dim} — update config + schema",
            )
            failures += 1
    except Exception as exc:  # noqa: BLE001
        _fail("Embeddings", f"{type(exc).__name__}: {exc}")
        failures += 1

    print("\n5) Database (Postgres + pgvector)")
    try:
        from backend.adapters.db.database import get_connection

        with get_connection() as conn:
            ver = conn.execute("SELECT version()").fetchone()[0]
            ext = conn.execute(
                "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
            ).fetchone()
        _ok("Database", ver.split(",")[0])
        if ext:
            _ok("pgvector", "extension available")
        else:
            _fail("pgvector", "not available on this Postgres")
            failures += 1
    except Exception as exc:  # noqa: BLE001
        _fail("Database", f"{type(exc).__name__}: {exc}")
        failures += 1

    print("\n" + ("All checks passed ✅" if failures == 0 else f"{failures} check(s) failed ❌"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
