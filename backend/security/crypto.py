"""Symmetric encryption for data at rest and signed session values.

Wraps Fernet (AES-128-CBC + HMAC). The key comes from config
(`TOKEN_ENCRYPTION_KEY`) and is never hardcoded. Used to:
  - encrypt OAuth tokens before they are persisted (encryption at rest), and
  - encrypt/authenticate the session cookie that names the logged-in user.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from backend.config import get_settings


class TokenCrypto:
    """Encrypt/decrypt short UTF-8 strings with a Fernet key."""

    def __init__(self, key: str) -> None:
        # Fernet validates the key format and raises if it is malformed.
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str, ttl: int | None = None) -> str | None:
        """Return the plaintext, or None if the token is invalid/tampered/expired.

        `ttl` (seconds) enforces a maximum age — used for session cookies so a
        leaked token can't be used forever. Data-at-rest (OAuth tokens) passes no
        ttl and never expires.
        """
        try:
            return self._fernet.decrypt(token.encode("utf-8"), ttl=ttl).decode("utf-8")
        except InvalidToken:
            return None


@lru_cache
def get_crypto() -> TokenCrypto:
    settings = get_settings()
    if not settings.token_encryption_key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"\n'
            "and add it to your .env."
        )
    return TokenCrypto(settings.token_encryption_key)
