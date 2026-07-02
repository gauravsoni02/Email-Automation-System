"""OAuth token persistence, behind a repository interface.

Phase 1 uses an encrypted-file implementation so auth works before Postgres is
provisioned. In Phase 2 this interface gets a Postgres-backed implementation
(the `users` table) and callers do not change — they depend on `TokenStore`.

Tokens are ALWAYS stored encrypted at rest (Fernet). The plaintext OAuth JSON
never touches disk.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

from backend.config import get_settings
from backend.security.crypto import get_crypto


class TokenStore(ABC):
    """Stores/retrieves a user's OAuth credential JSON, encrypted at rest."""

    @abstractmethod
    def save(self, user_id: str, token_json: str) -> None: ...

    @abstractmethod
    def load(self, user_id: str) -> str | None: ...

    @abstractmethod
    def exists(self, user_id: str) -> bool: ...


class EncryptedFileTokenStore(TokenStore):
    """Interim Phase-1 store: a JSON file of {user_id: encrypted_token_json}.

    The file is written atomically and lives outside version control
    (see .gitignore). Replaced by a Postgres repository in Phase 2.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._crypto = get_crypto()

    def _read_all(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_all(self, data: dict[str, str]) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic on the same filesystem

    def save(self, user_id: str, token_json: str) -> None:
        data = self._read_all()
        data[user_id] = self._crypto.encrypt(token_json)
        self._write_all(data)

    def load(self, user_id: str) -> str | None:
        encrypted = self._read_all().get(user_id)
        if encrypted is None:
            return None
        return self._crypto.decrypt(encrypted)

    def exists(self, user_id: str) -> bool:
        return user_id in self._read_all()


class PostgresTokenStore(TokenStore):
    """Phase-2 store: encrypted OAuth JSON in the `users.encrypted_token` column.

    Same encryption-at-rest guarantee as the file store; the token JSON is
    Fernet-encrypted before it ever reaches the database.
    """

    def __init__(self) -> None:
        # Imported lazily so the file store has no hard dependency on psycopg.
        from backend.adapters.db.repositories import UserRepository

        self._users = UserRepository()
        self._crypto = get_crypto()

    def save(self, user_id: str, token_json: str) -> None:
        self._users.set_token(user_id, self._crypto.encrypt(token_json))

    def load(self, user_id: str) -> str | None:
        encrypted = self._users.get_token(user_id)
        if encrypted is None:
            return None
        return self._crypto.decrypt(encrypted)

    def exists(self, user_id: str) -> bool:
        return self._users.get_token(user_id) is not None


def get_token_store() -> TokenStore:
    """Factory for the active token store.

    Uses Postgres when DATABASE_URL is configured (Phase 2+), otherwise falls
    back to the interim encrypted-file store (Phase 1 / no DB yet). Callers are
    unaffected — they depend on the TokenStore interface.
    """
    settings = get_settings()
    if settings.database_url:
        return PostgresTokenStore()
    return EncryptedFileTokenStore(settings.token_store_path)
