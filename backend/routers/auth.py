"""OAuth routes: start login, handle Google's callback, logout, whoami.

CSRF protection: the `state` returned by Google's auth URL is stored server-side
at login and validated on callback. On success we resolve the account email
(via Gmail getProfile), persist encrypted credentials, and set an encrypted
session cookie naming the user.

State store note: this is an in-memory set, which is correct for the single
FastAPI process used in dev. It moves to a persisted store alongside the Postgres
migration in Phase 2 if we run multiple workers.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from backend.adapters.gmail.client import GmailAdapter, GmailError
from backend.adapters.google.oauth import GoogleOAuthService
from backend.config import Settings
from backend.dependencies import (
    SESSION_COOKIE,
    crypto_dep,
    current_user_id,
    oauth_service_dep,
    settings_dep,
)
from backend.models.schemas import WhoAmIResponse
from backend.security.crypto import TokenCrypto

router = APIRouter(prefix="/auth", tags=["auth"])

# state -> (creation timestamp, PKCE code_verifier). Entries expire to bound
# memory + the replay window.
_STATE_TTL_SECONDS = 600
_pending_states: dict[str, tuple[float, str | None]] = {}
# cookie that binds the OAuth `state` to the browser that started login (CSRF).
OAUTH_STATE_COOKIE = "aegis_oauth_state"


def _remember_state(state: str, code_verifier: str | None) -> None:
    now = time.time()
    # opportunistic cleanup of expired states
    for s, (ts, _) in list(_pending_states.items()):
        if now - ts > _STATE_TTL_SECONDS:
            _pending_states.pop(s, None)
    _pending_states[state] = (now, code_verifier)


def _consume_state(state: str) -> tuple[bool, str | None]:
    """Pop the state; return (is_valid, code_verifier)."""
    entry = _pending_states.pop(state, None)
    if entry is None:
        return False, None
    ts, code_verifier = entry
    return (time.time() - ts) <= _STATE_TTL_SECONDS, code_verifier


@router.get("/login")
def login(
    oauth: GoogleOAuthService = Depends(oauth_service_dep),
    settings: Settings = Depends(settings_dep),
) -> RedirectResponse:
    """Redirect the user to Google's consent screen."""
    auth_url, state, code_verifier = oauth.authorization_url()
    _remember_state(state, code_verifier)
    resp = RedirectResponse(auth_url)
    # Bind state to this browser so the callback can reject a forged/mismatched
    # state (login CSRF / session fixation).
    resp.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
        max_age=_STATE_TTL_SECONDS,
    )
    return resp


@router.get("/callback")
def callback(
    code: str = Query(...),
    state: str = Query(...),
    oauth: GoogleOAuthService = Depends(oauth_service_dep),
    crypto: TokenCrypto = Depends(crypto_dep),
    settings: Settings = Depends(settings_dep),
    state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE),
) -> RedirectResponse:
    """Handle Google's redirect: validate state, exchange code, persist creds,
    then hand the session token to the Streamlit frontend and redirect there.

    Note: the token is passed to the frontend via a query param because the API
    and UI are separate origins/processes; over localhost in dev this is fine.
    The token is also set as an HttpOnly cookie for direct API use.
    """
    # The state must match BOTH the server-side record and the browser cookie set
    # at login — otherwise it's a forged/mismatched callback (login CSRF).
    if not state_cookie or state_cookie != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state mismatch.",
        )
    valid, code_verifier = _consume_state(state)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state.",
        )

    try:
        credentials = oauth.exchange_code(
            code=code, state=state, code_verifier=code_verifier
        )
    except Exception as exc:  # noqa: BLE001 - invalid/expired/reused code
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth code exchange failed. Please start login again.",
        ) from exc

    # Identify the account (gmail.readonly is sufficient for getProfile).
    try:
        user_id = GmailAdapter(credentials).get_profile_email()
    except GmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify Google account.",
        ) from exc
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google account has no email address.",
        )

    oauth.persist(user_id, credentials)

    session_token = crypto.encrypt(user_id)
    redirect = RedirectResponse(
        url=f"{settings.frontend_url}/?token={session_token}"
    )
    redirect.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=settings.environment != "development",
        max_age=60 * 60 * 24 * 7,
    )
    redirect.delete_cookie(OAUTH_STATE_COOKIE)
    return redirect


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "logged_out"}


@router.get("/whoami", response_model=WhoAmIResponse)
def whoami(user_id: str = Depends(current_user_id)) -> WhoAmIResponse:
    return WhoAmIResponse(user_id=user_id)
