import streamlit as st


def select_option(key, value):
    st.session_state[key] = value


def option_buttons(label, options, key):
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]
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


def navigate(page, person_id=None, action=None):
    st.session_state.page = page
    if person_id is not None:
        st.session_state.selected_person = person_id
        if page == "People" and action == "Find people":
            st.session_state.directory_target = person_id
    if action is not None:
        st.session_state.people_action = action


def redirect(page, person_id=None, action=None):
    st.session_state.navigation_request = (page, person_id, action)
    st.rerun()
