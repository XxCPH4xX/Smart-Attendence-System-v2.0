from pathlib import Path

import streamlit as st
from streamlit.components.v1 import declare_component

from backend.auth import digest
from backend.browser_sessions import cookie_name
from backend.config import get_settings
from frontend.client import request

session_bridge = declare_component(
    "browser_session", path=str(Path(__file__).parent / "components" / "session")
)


def restore_session():
    if st.session_state.get("browser_session_checked"):
        return
    st.session_state.browser_session_checked = True
    token = st.context.cookies.get(cookie_name(get_settings()))
    if token and not st.session_state.get("token"):
        st.session_state.token = token


def sync_browser_session():
    if not st.context.headers.get("Origin"):
        return
    token = st.session_state.get("token")
    if token:
        fingerprint = digest(token)
        if st.session_state.get("browser_session_saved") == fingerprint:
            return
        if st.context.cookies.get(cookie_name(get_settings())) == token:
            st.session_state.browser_session_saved = fingerprint
            return
        if not st.session_state.get("browser_session_ticket"):
            st.session_state.browser_session_ticket = request(
                "POST", "/auth/browser-session-ticket"
            )["ticket"]
        operation = st.session_state.browser_session_ticket
        endpoint = "/auth/browser-session"
    else:
        operation = st.session_state.get("clear_browser_cookie")
        if not operation:
            return
        endpoint = "/auth/browser-session/clear"
    with st.container(key="browser_session_bridge"):
        result = session_bridge(
            endpoint=get_settings().api_url.rstrip("/") + endpoint,
            ticket=operation if token else "",
            operation=operation,
            key="browser_session_cookie",
            default=None,
        )
    if not result or result.get("operation") != operation:
        return
    if result.get("ok"):
        if token:
            st.session_state.browser_session_saved = fingerprint
        st.session_state.pop("browser_session_ticket", None)
        st.session_state.pop("clear_browser_cookie", None)
    else:
        st.warning("Your browser could not remember this sign-in. Check that cookies are allowed.")
        if st.button("Retry saving sign-in"):
            st.session_state.pop("browser_session_ticket", None)
            st.rerun()
