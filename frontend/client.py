import httpx
import streamlit as st

from backend.config import get_settings


class APIError(Exception):
    pass


def request(method, path, **kwargs):
    headers = (
        {"Authorization": f"Bearer {st.session_state.token}"}
        if st.session_state.get("token")
        else {}
    )
    try:
        with httpx.Client(base_url=get_settings().api_url, headers=headers, timeout=120) as client:
            response = client.request(method, path, **kwargs)
    except httpx.HTTPError as error:
        raise APIError("The backend is unavailable. Start uvicorn and try again.") from error
    if response.status_code == 401 and path != "/auth/login":
        clear_session()
        st.rerun()
    if response.is_error:
        try:
            detail = response.json().get("detail", "Request failed")
            if isinstance(detail, list):
                detail = "; ".join(
                    f"{'.'.join(str(x) for x in d['loc'][1:])}: {d['msg']}" for d in detail
                )
        except ValueError:
            detail = f"Request failed ({response.status_code})"
        raise APIError(str(detail))
    if response.status_code == 204:
        return None
    if "application/json" in response.headers.get("content-type", ""):
        return response.json()
    return response.content


def clear_session():
    processor = st.session_state.get("processor")
    if processor:
        processor.close()
    st.session_state.clear()


def can(permission):
    return permission in st.session_state.user["permissions"]


def people_options(category=None, active=None):
    parameters = {"limit": 500}
    if category:
        parameters["category"] = category
    if active is not None:
        parameters["active"] = active
    response = request("GET", "/people", params=parameters)
    # Load subsequent pages for rosters instead of silently omitting larger institutions.
    items = response["items"]
    while len(items) < response["total"]:
        parameters["offset"] = len(items)
        items.extend(request("GET", "/people", params=parameters)["items"])
    return {p["id"]: p for p in items}


def person_label(person):
    return f"{person['full_name']} · {person['institutional_id']}"
