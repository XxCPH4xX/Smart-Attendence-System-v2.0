import streamlit as st

CATEGORY_PAGES = {"Students": "student", "Teachers": "teacher", "Staff": "staff"}
PAGE_CATEGORIES = {value: key for key, value in CATEGORY_PAGES.items()}


def open_page(page, section=None, person_id=None, filters=None):
    st.session_state.pop("pending_confirmation", None)
    if st.session_state.get("page") != page or section == "Directory":
        st.session_state.pop("profile_id", None)
    st.session_state.page = page
    if section is not None:
        st.session_state["section_" + page] = section
    if person_id is not None:
        st.session_state.profile_id = person_id
        st.session_state.selected_person = person_id
    if filters is not None:
        for key in list(st.session_state):
            if str(key).startswith("history_"):
                del st.session_state[key]
        st.session_state.page_filters = filters
    else:
        st.session_state.pop("page_filters", None)


def section_tabs(options, page):
    with st.container(key="section_tabs_" + page):
        return option_buttons("", options, key="section_" + page)


def select_option(key, value):
    st.session_state[key] = value


def option_buttons(label, options, key):
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]
    if label:
        st.caption(label)
    for column, option in zip(st.columns(len(options)), options, strict=True):
        column.button(
            option,
            key=f"{key}_{option}",
            type="primary" if st.session_state[key] == option else "secondary",
            use_container_width=True,
            on_click=select_option,
            args=(key, option),
        )
    return st.session_state[key]
