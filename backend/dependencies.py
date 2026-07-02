"""FastAPI dependency providers: config, token store, OAuth service, and the
authenticated-user resolver (from the encrypted session cookie).

Keeping these here means routers stay thin and every data access is scoped to the
authenticated user (no cross-user access).
"""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status

from backend.adapters.db.token_store import TokenStore, get_token_store
from backend.adapters.google.oauth import GoogleOAuthService, OAuthNotConfigured
from backend.config import Settings, get_settings
from backend.security.crypto import TokenCrypto, get_crypto

# Cookie alias must be a constant at function-definition time; keep it in sync
# with Settings.session_cookie_name (same default).
SESSION_COOKIE = get_settings().session_cookie_name


def settings_dep() -> Settings:
    return get_settings()


def token_store_dep() -> TokenStore:
    return get_token_store()


def crypto_dep() -> TokenCrypto:
    try:
        return get_crypto()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def oauth_service_dep(
    settings: Settings = Depends(settings_dep),
    store: TokenStore = Depends(token_store_dep),
) -> GoogleOAuthService:
    try:
        return GoogleOAuthService(settings, store)
    except OAuthNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


def current_user_id(
    settings: Settings = Depends(settings_dep),
    crypto: TokenCrypto = Depends(crypto_dep),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> str:
    """Resolve the logged-in user id from the encrypted session cookie.

    Returns 401 if the cookie is missing, tampered with, or expired (decrypt with
    a TTL fails).
    """
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated."
        )
    user_id = crypto.decrypt(session, ttl=settings.session_ttl_seconds)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session."
        )
    return user_id


def _load_credentials(oauth: GoogleOAuthService, user_id: str):
    creds = oauth.load_credentials(user_id)
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No stored credentials; please log in again.",
        )
    return creds


def gmail_adapter_dep(
    user_id: str = Depends(current_user_id),
    oauth: GoogleOAuthService = Depends(oauth_service_dep),
):
    from backend.adapters.gmail.client import GmailAdapter

    return GmailAdapter(_load_credentials(oauth, user_id))


def calendar_adapter_dep(
    user_id: str = Depends(current_user_id),
    oauth: GoogleOAuthService = Depends(oauth_service_dep),
):
    from backend.adapters.calendar.client import CalendarAdapter

    return CalendarAdapter(_load_credentials(oauth, user_id))
