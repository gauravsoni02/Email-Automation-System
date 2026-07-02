"""Gmail adapter.

`list_emails` / `read_email` are read-only (Phase 1). `send_message` (Phase 5) is
the ONLY mutating method and is called exclusively by the approval executor — i.e.
after a pending action has been explicitly approved by the authenticated user.
It is never invoked autonomously by the agent or a processor.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.models.schemas import EmailDetail, EmailSummary


class GmailError(RuntimeError):
    """Raised when the Gmail API call fails; carries a safe message."""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def _extract_plain_text(payload: dict) -> str:
    """Walk the MIME tree and return the first text/plain part (fallback: html)."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime == "text/plain" and body.get("data"):
        return _decode_body(body["data"])

    html_fallback = ""
    for part in payload.get("parts", []) or []:
        text = _extract_plain_text(part)
        if text and part.get("mimeType") == "text/plain":
            return text
        if text and not html_fallback:
            html_fallback = text
    if not html_fallback and mime == "text/html" and body.get("data"):
        html_fallback = _decode_body(body["data"])
    return html_fallback


class GmailAdapter:
    def __init__(self, credentials: Credentials) -> None:
        # cache_discovery=False avoids noisy warnings and file-cache issues.
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def get_profile_email(self) -> str:
        """The authenticated account's address (needs only gmail.readonly)."""
        try:
            profile = self._service.users().getProfile(userId="me").execute()
        except HttpError as exc:
            raise GmailError("Failed to read Gmail profile.") from exc
        return profile.get("emailAddress", "")

    def list_emails(self, max_results: int = 10) -> list[EmailSummary]:
        try:
            listing = (
                self._service.users()
                .messages()
                .list(userId="me", maxResults=max_results, labelIds=["INBOX"])
                .execute()
            )
            summaries: list[EmailSummary] = []
            for ref in listing.get("messages", []):
                msg = (
                    self._service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=ref["id"],
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    )
                    .execute()
                )
                headers = msg.get("payload", {}).get("headers", [])
                summaries.append(
                    EmailSummary(
                        id=msg["id"],
                        thread_id=msg.get("threadId", ""),
                        sender=_header(headers, "From"),
                        subject=_header(headers, "Subject"),
                        snippet=msg.get("snippet", ""),
                        date=_header(headers, "Date"),
                        unread="UNREAD" in msg.get("labelIds", []),
                    )
                )
            return summaries
        except HttpError as exc:
            raise GmailError("Failed to list emails.") from exc

    def send_message(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
    ) -> str:
        """Send an email. GATED: only the approval executor calls this, after a
        pending action is approved. Returns the sent message id.

        `thread_id` (the Gmail thread) keeps the reply in the original thread.
        """
        # Strip CR/LF from header values to prevent email header injection
        # (e.g. a smuggled "Bcc:") via an edited subject/recipient.
        safe_to = to.replace("\r", "").replace("\n", "").strip()
        safe_subject = subject.replace("\r", " ").replace("\n", " ").strip()
        message = MIMEText(body)
        message["to"] = safe_to
        message["subject"] = safe_subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        request_body: dict = {"raw": raw}
        if thread_id:
            request_body["threadId"] = thread_id
        try:
            sent = (
                self._service.users()
                .messages()
                .send(userId="me", body=request_body)
                .execute()
            )
        except HttpError as exc:
            raise GmailError("Failed to send email.") from exc
        return sent.get("id", "")

    def read_email(self, message_id: str) -> EmailDetail:
        try:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except HttpError as exc:
            raise GmailError("Failed to read email.") from exc

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        return EmailDetail(
            id=msg["id"],
            thread_id=msg.get("threadId", ""),
            sender=_header(headers, "From"),
            to=_header(headers, "To"),
            subject=_header(headers, "Subject"),
            snippet=msg.get("snippet", ""),
            date=_header(headers, "Date"),
            unread="UNREAD" in msg.get("labelIds", []),
            body=_extract_plain_text(payload),
        )
