"""Google OAuth 2.0 flow and credential lifecycle.

Responsibilities:
  - Build the authorization URL with a CSRF `state` value.
  - Validate `state` on callback and exchange the code for tokens.
  - Persist credentials (encrypted) via the `TokenStore`.
  - Load credentials for a user, transparently refreshing + re-persisting them.

Minimal scopes only (readonly mail/calendar + compose/events) per CLAUDE.md.
Phase 1 is read-only; the compose/events scopes are requested now so the Phase 5
gated send/create path won't require re-consent, but nothing here sends anything.
"""

from __future__ import annotations

import json
import os

# Google may return scopes in a different order / add `openid`; relax oauthlib's
# strict scope-equality check so the token exchange doesn't spuriously fail.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from google.auth.exceptions import RefreshError  # noqa: E402
from google.auth.transport.requests import Request  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from google_auth_oauthlib.flow import Flow  # noqa: E402

from backend.adapters.db.token_store import TokenStore
from backend.config import Settings

# xAI/Google note: OAuth requires HTTPS by default. For local dev over http we
# rely on the loopback redirect (http://localhost), which Google permits.


def _client_config(settings: Settings) -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


class OAuthNotConfigured(RuntimeError):
    pass


class GoogleOAuthService:
    """Owns the OAuth handshake and credential refresh. Provider-agnostic
    callers (Gmail/Calendar adapters) receive ready-to-use `Credentials`.
    """

    def __init__(self, settings: Settings, token_store: TokenStore) -> None:
        if not (settings.google_client_id and settings.google_client_secret):
            raise OAuthNotConfigured(
                "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set. Add them "
                "to your .env (see README Phase 1 setup)."
            )
        self._settings = settings
        self._store = token_store
        self._scopes = settings.google_scopes_list

    def _make_flow(self, state: str | None = None) -> Flow:
        return Flow.from_client_config(
            _client_config(self._settings),
            scopes=self._scopes,
            redirect_uri=self._settings.google_redirect_uri,
            state=state,
        )

    def authorization_url(self) -> tuple[str, str, str | None]:
        """Return (auth_url, state, code_verifier).

        The caller must persist BOTH `state` (CSRF) and `code_verifier` (PKCE)
        and supply them back at the callback — Google requires the verifier that
        matches the challenge sent here.
        """
        flow = self._make_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",  # request a refresh token
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url, state, getattr(flow, "code_verifier", None)

    def exchange_code(
        self, code: str, state: str, code_verifier: str | None = None
    ) -> Credentials:
        """Exchange the auth code for credentials. `state` was already validated
        by the caller; `code_verifier` completes the PKCE handshake.
        """
        flow = self._make_flow(state=state)
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        return flow.credentials

    def persist(self, user_id: str, credentials: Credentials) -> None:
        self._store.save(user_id, credentials.to_json())

    def load_credentials(self, user_id: str) -> Credentials | None:
        """Load a user's credentials, refreshing + re-persisting if expired."""
        raw = self._store.load(user_id)
        if raw is None:
            return None
        creds = Credentials.from_authorized_user_info(json.loads(raw), self._scopes)
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # refresh token revoked/expired -> treat as no credentials (401)
                return None
            self._store.save(user_id, creds.to_json())
        return creds
