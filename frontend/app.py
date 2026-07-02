"""Streamlit frontend for Aegis Mail AI.

THIN UI ONLY (see CLAUDE.md guardrails): it renders API responses and posts user
actions to the FastAPI backend over HTTP. No business logic lives here.

Auth handoff: after Google OAuth the backend redirects here with ?token=<session>.
We keep it in the URL query param so a browser refresh stays logged in (Streamlit
clears session_state on a full refresh), and send it as the session cookie on
every call. GET reads are cached briefly and the cache is cleared after any action
so the UI stays snappy but current.

Run with:  streamlit run frontend/app.py
"""

from __future__ import annotations

import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
SESSION_COOKIE = os.environ.get("AEGIS_SESSION_COOKIE", "aegis_session")

st.set_page_config(page_title="Aegis Mail AI", page_icon="📬", layout="wide")


# --------------------------------------------------------------------------- #
# API helpers (cached GETs + cache-invalidating POSTs)
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=15, show_spinner=False)
def _cached_get(token: str, path: str, params_tuple: tuple) -> tuple[int, object]:
    cookies = {SESSION_COOKIE: token} if token else {}
    try:
        r = requests.get(
            f"{BACKEND_URL}{path}", params=dict(params_tuple), cookies=cookies, timeout=60
        )
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text
    except requests.RequestException as exc:
        return 0, str(exc)


def get(path: str, **params) -> tuple[int, object]:
    token = st.session_state.get("token") or ""
    return _cached_get(token, path, tuple(sorted(params.items())))


def post(path: str, json: dict | None = None, **params) -> tuple[int, object]:
    token = st.session_state.get("token") or ""
    cookies = {SESSION_COOKIE: token} if token else {}
    try:
        r = requests.post(
            f"{BACKEND_URL}{path}", params=params, json=json, cookies=cookies, timeout=120
        )
        _cached_get.clear()  # any mutation may change reads -> refresh
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text
    except requests.RequestException as exc:
        return 0, str(exc)


# --------------------------------------------------------------------------- #
# Auth (token persisted in the URL so refresh keeps the session)
# --------------------------------------------------------------------------- #
if "token" in st.query_params and not st.session_state.get("token"):
    st.session_state["token"] = st.query_params["token"]
if st.session_state.get("token"):
    # keep the token in the URL for refresh-persistence
    st.query_params["token"] = st.session_state["token"]


def current_user() -> str | None:
    if not st.session_state.get("token"):
        return None
    code, data = get("/auth/whoami")
    if code == 200 and isinstance(data, dict):
        return data.get("user_id")
    return None


def logout() -> None:
    post("/auth/logout")
    st.session_state.pop("token", None)
    st.query_params.clear()
    _cached_get.clear()
    st.rerun()


def login_screen() -> None:
    st.title("📬 Aegis Mail AI")
    st.caption("Personal inbox + calendar assistant with a human-in-the-loop safety gate.")
    st.write("")
    try:
        h = requests.get(f"{BACKEND_URL}/health", timeout=5).json()
        st.success(f"Backend online — LLM: {h['config']['llm_model']}")
    except requests.RequestException:
        st.error(f"Backend not reachable at {BACKEND_URL}. Start it with `uvicorn backend.main:app`.")
        return
    st.write("Connect your Google account to get started.")
    st.link_button("🔐 Sign in with Google", f"{BACKEND_URL}/auth/login", type="primary")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
CATEGORY_ICON = {
    "urgent": "🔴", "finance": "💰", "meeting": "📅", "personal": "👤",
    "work": "💼", "newsletter": "📰", "promotion": "🏷️", "notification": "🔔",
    "spam": "🚫", "other": "✉️",
}


def priority_color(p: int | None) -> str:
    if p is None:
        return "gray"
    if p >= 70:
        return "red"
    if p >= 40:
        return "orange"
    return "gray"


def render_email_row(e: dict, show_priority: bool = True) -> None:
    cat = (e.get("category") or "other").lower()
    icon = CATEGORY_ICON.get(cat, "✉️")
    subject = e.get("subject") or "(no subject)"
    unread = "🟢 " if e.get("unread") else ""
    eid = e.get("id") or e.get("email_id")
    with st.container(border=True):
        c1, c2 = st.columns([0.85, 0.15])
        with c1:
            st.markdown(f"**{unread}{icon} {subject}**")
            st.caption(f"From: {e.get('sender','')}")
            if e.get("summary_one_line"):
                st.write(e["summary_one_line"])
        with c2:
            if show_priority and e.get("priority") is not None:
                st.markdown(
                    f":{priority_color(e['priority'])}[**{e['priority']}**]  \n:gray[{cat}]"
                )
            else:
                st.caption(cat)
        with st.expander("Details & actions"):
            if e.get("summary_detailed"):
                st.write(e["summary_detailed"])
            b1, b2 = st.columns(2)
            if eid and b1.button("Open full email", key=f"open_{eid}"):
                code, data = get(f"/emails/{eid}")
                if code == 200 and isinstance(data, dict):
                    st.text_area("Body", data.get("body", ""), height=250, key=f"full_{eid}")
                else:
                    st.warning("Could not load full email.")
            if eid and b2.button("🤖 Draft reply", key=f"draft_{eid}", type="primary"):
                with st.spinner("Reading thread, checking calendar, drafting…"):
                    code, data = post("/agent/reply", json={"email_id": eid})
                if code == 200:
                    st.toast("Draft queued → see the Pending tab", icon="✅")
                    st.rerun()
                else:
                    st.error(f"Agent failed ({code}): {str(data)[:200]}")


# --------------------------------------------------------------------------- #
# Main app
# --------------------------------------------------------------------------- #
def app(user_id: str) -> None:
    with st.sidebar:
        st.title("📬 Aegis Mail AI")
        st.caption(f"Signed in as **{user_id}**")
        if st.button("🔄 Refresh", use_container_width=True):
            _cached_get.clear()
            st.rerun()
        st.divider()

        # LLM model switcher (70b = best quality, 8b-instant = higher daily limit)
        code, m = get("/models")
        if code == 200 and isinstance(m, dict) and m.get("available"):
            available = m["available"]
            active = m.get("active")
            idx = available.index(active) if active in available else 0
            choice = st.selectbox("🧠 LLM model", available, index=idx)
            if choice != active:
                c2, _ = post("/models/select", json={"model": choice})
                if c2 == 200:
                    _cached_get.clear()
                    st.toast(f"Switched to {choice}", icon="🧠")
                    st.rerun()
                else:
                    st.error("Could not switch model.")
        st.divider()

        st.subheader("Ingest")
        limit = st.slider("Emails to fetch", 1, 20, 5)
        if st.button("⚙️ Ingest & triage now", type="primary", use_container_width=True):
            with st.spinner("Fetching, embedding, and triaging…"):
                code, data = post("/ingest/sync", limit=limit)
            if code == 200:
                st.toast(f"Ingested: {data}", icon="✅")
                st.rerun()
            else:
                st.error(f"Ingest failed ({code}): {str(data)[:200]}")

        st.divider()
        st.subheader("Follow-ups")
        if st.button("🔔 Scan stale threads", use_container_width=True):
            with st.spinner("Scanning & drafting follow-ups…"):
                code, data = post("/followup/scan")
            if code == 200:
                st.toast(f"Follow-up: {data}", icon="✅")
                st.rerun()
            else:
                st.error(f"Scan failed ({code}).")

        st.divider()
        if st.button("🚪 Log out", use_container_width=True):
            logout()

    tab_digest, tab_inbox, tab_search, tab_chat, tab_tasks, tab_pending = st.tabs(
        ["📥 Digest", "📨 Inbox", "🔍 Search", "💬 Chat", "✅ Tasks", "📤 Pending"]
    )

    with tab_digest:
        st.subheader("Your morning digest")
        code, d = get("/digest")
        if code == 200 and isinstance(d, dict):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**🔥 Top priorities**")
                if not d["top_priorities"]:
                    st.caption("Nothing yet — run **Ingest & triage**.")
                for e in d["top_priorities"]:
                    st.markdown(f"- `{e['priority']}` **{e['subject']}** — {e.get('summary','')}")
                st.markdown("**📅 Upcoming meetings**")
                if not d["upcoming_meetings"]:
                    st.caption("None today.")
                for m in d["upcoming_meetings"]:
                    st.markdown(f"- {m['summary']} ({m.get('start','')})")
            with c2:
                st.markdown("**📤 Pending replies (awaiting approval)**")
                if not d["pending_replies"]:
                    st.caption("None.")
                for p in d["pending_replies"]:
                    st.markdown(f"- {p['type']} → {p.get('to','')}: {p.get('subject','')}")
                st.markdown("**✅ Tasks due**")
                if not d["tasks_due"]:
                    st.caption("None.")
                for t in d["tasks_due"][:10]:
                    due = f" (due {t['due_date']})" if t.get("due_date") else ""
                    st.markdown(f"- {t['description']}{due}")
        else:
            st.error(f"Failed to load digest ({code}).")

    with tab_inbox:
        st.subheader("Inbox (most recent)")
        code, rows = get("/triaged", by_priority=False, limit=30)
        if code == 200 and isinstance(rows, list):
            for e in rows:
                render_email_row(e, show_priority=False)
        else:
            st.error(f"Failed to load inbox ({code}).")

    with tab_search:
        st.subheader("Search your inbox")
        with st.form("search_form"):
            q = st.text_input("Query", placeholder="e.g. emails about the project setup")
            c1, c2, c3 = st.columns(3)
            category = c1.text_input("Category filter", placeholder="(optional)")
            sender = c2.text_input("Sender filter", placeholder="(optional)")
            unread_only = c3.checkbox("Unread only")
            submitted = st.form_submit_button("Search", type="primary")
        if submitted and q.strip():
            params = {"q": q, "unread_only": unread_only, "limit": 20}
            if category.strip():
                params["category"] = category.strip()
            if sender.strip():
                params["sender"] = sender.strip()
            code, results = get("/search", **params)
            if code == 200 and isinstance(results, list):
                if not results:
                    st.info("No matches.")
                for e in results:
                    st.caption(f"score: {e.get('score')}")
                    render_email_row(e, show_priority=False)
            elif code == 503:
                st.warning("Search needs a database + embeddings configured.")
            else:
                st.error(f"Search failed ({code}): {str(results)[:200]}")

    with tab_chat:
        st.subheader("Chat with your inbox")
        st.caption("e.g. \"what did Priya ask me?\" or \"any finance emails this week?\"")
        st.session_state.setdefault("chat_history", [])
        for m in st.session_state["chat_history"]:
            with st.chat_message(m["role"]):
                st.write(m["content"])
        prompt = st.chat_input("Ask about your emails…")
        if prompt:
            st.session_state["chat_history"].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Searching your inbox…"):
                    code, data = post(
                        "/chat",
                        json={
                            "message": prompt,
                            "conversation_id": st.session_state.get("conversation_id"),
                        },
                    )
                if code == 200 and isinstance(data, dict):
                    st.session_state["conversation_id"] = data["conversation_id"]
                    st.write(data["answer"])
                    if data.get("citations"):
                        with st.expander(f"Sources ({len(data['citations'])})"):
                            for i, c in enumerate(data["citations"], 1):
                                st.caption(f"[{i}] {c.get('sender','')} — {c.get('subject','')}")
                    st.session_state["chat_history"].append(
                        {"role": "assistant", "content": data["answer"]}
                    )
                else:
                    st.error(f"Chat failed ({code}): {str(data)[:200]}")

    with tab_tasks:
        st.subheader("Extracted tasks")
        code, tasks = get("/tasks")
        if code == 200 and isinstance(tasks, list):
            if not tasks:
                st.info("No tasks extracted yet.")
            for t in tasks:
                due = f" — due {t['due_date']}" if t.get("due_date") else ""
                st.checkbox(f"{t['description']}{due}", key=f"task_{t['id']}")
        else:
            st.error(f"Failed to load tasks ({code}).")

    with tab_pending:
        st.subheader("Review queue — approve, edit, or reject")
        st.caption(
            "The human-in-the-loop safety gate. Nothing is sent until you approve. "
            "Editing the subject/body changes exactly what gets sent."
        )
        code, pend = get("/actions")
        if code == 200 and isinstance(pend, list):
            if not pend:
                st.info("No pending actions. Use **🤖 Draft reply** on an email.")
            for a in pend:
                p = a["payload"]
                aid = a["id"]
                with st.container(border=True):
                    st.markdown(f"**✉️ {a['action_type']}** → {p.get('to','')}")
                    if p.get("proposed_times"):
                        st.caption("Proposed times: " + ", ".join(p["proposed_times"]))
                    subj = st.text_input("Subject", p.get("subject", ""), key=f"subj_{aid}")
                    body = st.text_area("Body", p.get("body", ""), height=200, key=f"body_{aid}")
                    c1, c2, _ = st.columns([0.3, 0.3, 0.4])
                    if c1.button("✅ Approve & send", key=f"appr_{aid}", type="primary"):
                        with st.spinner("Sending…"):
                            code2, data2 = post(
                                f"/actions/{aid}/approve", json={"subject": subj, "body": body}
                            )
                        if code2 == 200:
                            mid = data2.get("result", {}).get("gmail_message_id", "") if isinstance(data2, dict) else ""
                            st.toast(f"Sent ✅ ({mid})", icon="📧")
                            st.rerun()
                        else:
                            st.error(f"Send failed ({code2}): {str(data2)[:200]}")
                    if c2.button("🗑️ Reject", key=f"rej_{aid}"):
                        code2, _ = post(f"/actions/{aid}/reject")
                        if code2 == 200:
                            st.toast("Draft discarded", icon="🗑️")
                            st.rerun()
                        else:
                            st.error(f"Reject failed ({code2}).")
        else:
            st.error(f"Failed to load pending actions ({code}).")


# --------------------------------------------------------------------------- #
user = current_user()
if user:
    app(user)
else:
    login_screen()
