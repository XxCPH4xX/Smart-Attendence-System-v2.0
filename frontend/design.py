from html import escape

import streamlit as st

STATUS_COLORS = {
    "present": "#16856b",
    "late": "#b7791f",
    "absent": "#ca4d59",
    "pending_verification": "#b7791f",
    "on_leave": "#6876bd",
    "excused": "#64748b",
    "holiday": "#94a3b8",
}


def apply_theme():
    st.html("""<style>
    :root { --ink:#18243d; --muted:#748097; --line:#e7ebf2; --brand:#5063dc; }
    .stApp { background:#f5f7fb; color:var(--ink); }
    [data-testid="stHeader"] { background:transparent; }
    [data-testid="stMainBlockContainer"] { padding:2rem 2.6rem 3rem; max-width:1600px; }
    [data-testid="stSidebar"][aria-expanded="true"] { background:#fff; border-right:1px solid var(--line); min-width:244px; max-width:244px; }
    [data-testid="stSidebar"][aria-expanded="false"] {min-width:0!important;max-width:0!important;width:0!important;margin-left:0!important;}
    [data-testid="stSidebarUserContent"] { padding:1.5rem 1rem; }
    [data-testid="stSidebar"] .stButton button { justify-content:flex-start; border:0; padding:.6rem .85rem; border-radius:8px; font-size:.88rem; }
    [data-testid="stSidebar"] button[kind="secondary"] { background:transparent; color:#65708a; }
    [data-testid="stSidebar"] button[kind="primary"] { background:#edf0ff; color:#4657cf; border:0; box-shadow:inset 3px 0 #5063dc; }
    h1 { font-size:1.85rem!important; letter-spacing:-.04em; font-weight:750!important; }
    h2 { font-size:1.32rem!important; letter-spacing:-.025em; }
    h3 { font-size:1.1rem!important; }
    p, label { line-height:1.5; }
    .stButton button, .stDownloadButton button, .stFormSubmitButton button { border-radius:8px; min-height:2.5rem; font-weight:500; transition:background .15s ease; }
    button[kind="primary"] { background:var(--brand); border-color:var(--brand); }
    button:focus-visible, input:focus-visible { outline:3px solid #a5b4fc!important; outline-offset:2px; }
    [data-testid="stVerticalBlockBorderWrapper"]:has(>div>[class*="st-key-card_"]) { border:1px solid var(--line); border-radius:12px; background:#fff; }
    [data-testid="stMetric"] { padding:.3rem 0; }
    [data-testid="stMetricValue"] { font-size:1.9rem; font-weight:700; }
    [data-testid="stMetricLabel"] { color:#6f7c93; font-size:.8rem; }
    [data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] { background:#fff!important; border-color:#e0e5ee!important; border-radius:8px; }
    [data-testid="stExpander"] { background:#fff; border-radius:10px; }
    [data-testid="stDataFrame"] { border-radius:10px; overflow:hidden; border:1px solid var(--line); }
    [data-testid="stTabs"] [role="tablist"] { gap:1.4rem; background:transparent; border-bottom:1px solid var(--line); }
    [data-testid="stTabs"] [role="tab"] { font-size:.88rem; }
    .sa-brand {display:flex; align-items:center; gap:.7rem; margin-bottom:1.5rem; font-weight:750; font-size:1.15rem; letter-spacing:-.035em;}
    .sa-mark {display:grid; place-items:center; width:36px; height:36px; background:#5063dc; color:white; border-radius:10px; font-size:20px;}
    .sa-nav-group {font-size:.64rem; letter-spacing:.13em; color:#a0a9ba; font-weight:650; margin:1.25rem .8rem .5rem;}
    .sa-eyebrow {font-size:.7rem; letter-spacing:.09em; color:#7e88a0; text-transform:uppercase; margin-bottom:.4rem;}
    .sa-title {font-size:1.85rem; font-weight:750; letter-spacing:-.045em; color:#18243d; margin:0; line-height:1.2;}
    .sa-description {color:#7a8599; font-size:.88rem; margin:.5rem 0 1.25rem;}
    .sa-badge {display:inline-flex; align-items:center; gap:.35rem; padding:4px 9px; border-radius:6px; font-size:.73rem; font-weight:600; background:#eef2ff; color:#5262cb;}
    .sa-badge.good {background:#eaf7f1;color:#16856b;} .sa-badge.warn {background:#fff5e5;color:#a77720;} .sa-badge.bad {background:#fff0f1;color:#bd4d5d;} .sa-badge.muted {background:#f0f2f7;color:#778299;}
    .sa-avatar {width:42px;height:42px;border-radius:12px;background:#eef1ff;color:#6370c9;display:flex;align-items:center;justify-content:center;font-weight:650;font-size:.85rem;flex-shrink:0;}
    .sa-person {display:flex;align-items:center;gap:.75rem;} .sa-person strong {font-size:.86rem;font-weight:600;} .sa-person small {display:block;color:#8c95a7;font-size:.75rem;margin-top:2px;}
    .sa-empty {padding:2rem 1.5rem;text-align:center;background:white;border:1px dashed #d9dfec;border-radius:12px;margin:.5rem 0 1rem;}
    .sa-empty strong {display:block;margin:.6rem 0;font-size:1rem;} .sa-empty p {color:#8a94a7;font-size:.85rem;margin:0;}
    .sa-step {display:flex;gap:.5rem;align-items:center;font-size:.76rem;color:#94a0b4;margin:.5rem 0 1rem;} .sa-step.active {color:#5063dc;font-weight:600;} .sa-step span {width:26px;height:26px;border:1px solid #dce2f0;border-radius:50%;display:grid;place-items:center;} .sa-step.active span{background:#5063dc;color:white;border-color:#5063dc;}
    .st-key-topbar {margin-bottom:1.25rem;}
    .st-key-topbar [data-testid="stPopoverButton"] {justify-content:flex-start;}
    .st-key-topbar > [data-testid="stHorizontalBlock"] {align-items:center;flex-wrap:wrap;gap:12px;}
    .st-key-topbar [data-testid="stColumn"]:first-child {flex:1 1 200px!important;min-width:160px!important;}
    .st-key-topbar [data-testid="stColumn"]:has(.st-key-topbar_bell) {flex:0 0 40px!important;min-width:40px!important;margin-left:auto;}
    .st-key-topbar [data-testid="stColumn"]:has(.st-key-topbar_account) {flex:0 1 180px!important;min-width:140px!important;}
    .st-key-topbar_bell [data-testid="stPopoverButton"] {border-radius:50%;width:40px;height:40px;min-height:40px;padding:0;justify-content:center;}
    .st-key-topbar_bell [data-testid="stPopoverButton"] span {margin:0;}
    .st-key-topbar_bell [data-testid="stPopoverButton"] [data-testid="stMarkdownContainer"] {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
    .st-key-topbar_bell [data-testid="stPopoverButton"] > div:last-child {display:none;}
    .st-key-browser_session_bridge {display:none;}
    [data-testid="stPopoverBody"]:has([class*="st-key-person_actions_"]) {width:230px;max-width:calc(100vw - 24px);padding:8px;border:1px solid #e2e7ef;border-radius:12px;box-shadow:0 8px 24px #18243d14;}
    [class*="st-key-person_actions_"] {gap:2px;}
    [class*="st-key-person_actions_"] .stButton button {justify-content:flex-start;gap:10px;min-height:36px;padding:7px 10px;border:0;border-radius:6px;background:transparent;color:#35425a;font-weight:400;}
    [class*="st-key-person_actions_"] .stButton button:hover {background:#f1f4f9;color:#18243d;}
    [class*="st-key-person_actions_"] .stButton button > span, [class*="st-key-person_actions_"] [data-testid="stIconMaterial"] {margin:0;}
    [class*="st-key-person_actions_"] .stButton button:focus-visible {outline:2px solid #a5b4fc!important;outline-offset:-2px;}
    [class*="st-key-person_delete_"] {border-top:1px solid var(--line);padding-top:5px;margin-top:5px;}
    [class*="st-key-person_delete_"] .stButton button {color:#ba3e4d;}
    [class*="st-key-person_delete_"] .stButton button:hover {background:#fff0f2;color:#a72c3b;}
    [class*="st-key-section_tabs_"] {margin-bottom:.6rem;}
    [class*="st-key-section_tabs_"] button {border:0;background:transparent!important;color:#7a859b;border-radius:0;border-bottom:2px solid transparent;}
    [class*="st-key-section_tabs_"] button[kind="primary"] {color:#5063dc;border-bottom-color:#5063dc;}
    [class*="st-key-section_tabs_"] [data-testid="stHorizontalBlock"] {flex-wrap:wrap;gap:.5rem;}
    [class*="st-key-section_tabs_"] [data-testid="stColumn"] {flex:1 1 110px!important;min-width:100px!important;}
    [data-testid="stForm"] {background:white;border:1px solid var(--line);border-radius:12px;}
    [data-testid="stPopoverButton"] p, .stButton button p {font-size:.875rem;overflow-wrap:normal;word-break:normal;}
    @media(max-width:640px) { .st-key-topbar [data-testid="stColumn"]:first-child {flex:1 0 100%!important;} }
    @media(max-width:1000px) {
      [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-card_kpi_"]) {flex-wrap:wrap;}
      [data-testid="stColumn"]:has([class*="st-key-card_kpi_"]) {flex:1 1 180px!important;min-width:180px!important;}
    }
    @media(max-width:900px) { [data-testid="stMainBlockContainer"] {padding:3.5rem 1rem 2rem;} .sa-title{font-size:1.5rem;} }
    @media(prefers-reduced-motion:reduce) { * {transition:none!important;} }
    </style>""")


def heading(title, description="", breadcrumb="Workspace"):
    st.html(
        f'<div class="sa-eyebrow">{escape(breadcrumb)}</div><h1 class="sa-title">{escape(title)}</h1><p class="sa-description">{escape(description)}</p>'
    )


def badge(label, tone="muted"):
    if tone not in {"good", "warn", "bad", "muted"}:
        tone = "muted"
    st.html(f'<span class="sa-badge {tone}">{escape(label)}</span>')


def person_identity(person):
    initials = "".join(word[0] for word in person["full_name"].split()[:2]).upper()
    st.html(
        f'<div class="sa-person"><div class="sa-avatar">{escape(initials)}</div><div><strong>{escape(person["full_name"])}</strong><small>{escape(person["institutional_id"])}</small></div></div>'
    )


def empty(title, description):
    st.html(
        f'<div class="sa-empty"><span class="sa-badge">No records yet</span><strong>{escape(title)}</strong><p>{escape(description)}</p></div>'
    )


def metric(label, value, context="", *, destination=None, section=None, filters=None):
    with st.container(border=True, key="card_kpi_" + label):
        st.metric(label, value)
        if context:
            st.caption(context)
        if destination:
            from frontend.navigation import open_page

            st.button(
                "View " + label.lower(),
                key="kpi_" + label,
                type="tertiary",
                icon=":material/arrow_forward:",
                on_click=open_page,
                args=(destination, section),
                kwargs={"filters": filters},
            )


def flash():
    message = st.session_state.pop("notice", None)
    if message:
        st.toast(message, icon=":material/check_circle:")
        st.success(message)
    error = st.session_state.pop("notice_error", None)
    if error:
        st.error(error)


def confirmation(title, description, action, args=(), kwargs=None):
    st.session_state.pending_confirmation = (title, description, action, args, kwargs or {})


@st.dialog("Confirm action")
def _confirmation_dialog(title, description, action, args, kwargs):
    from frontend.client import APIError

    st.subheader(title)
    st.write(description)
    cancel, confirm = st.columns(2)
    if cancel.button("Cancel", use_container_width=True):
        st.session_state.pop("pending_confirmation", None)
        st.rerun()
    if confirm.button("Confirm", type="primary", use_container_width=True):
        try:
            action(*args, **kwargs)
        except APIError as error:
            st.error(str(error))
        else:
            st.session_state.pop("pending_confirmation", None)
            st.rerun()


def render_confirmation():
    pending = st.session_state.get("pending_confirmation")
    if pending:
        _confirmation_dialog(*pending)
