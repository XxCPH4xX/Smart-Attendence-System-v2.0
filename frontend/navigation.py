import streamlit as st


def navigate(page, person_id=None, action=None):
    st.session_state.page = page
    if person_id is not None:
        st.session_state.selected_person = person_id
        if page == "Take attendance":
            st.session_state.new_attendance_session = True
            st.session_state.quick_person_id = person_id
    if action is not None:
        st.session_state.people_action = action


def redirect(page, person_id=None, action=None):
    st.session_state.navigation_request = (page, person_id, action)
    st.rerun()
