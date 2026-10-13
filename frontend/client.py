import re

import httpx
import streamlit as st

from backend.config import get_settings


class APIError(Exception):
    pass


def validation_message(issue):
    fields = [str(part) for part in issue.get("loc", [])[1:] if isinstance(part, str)]
    field = fields[-1] if fields else ""
    labels = {
        "reason": "a reason",
        "username": "a username",
        "password": "a password",
        "new_password": "a new password",
        "institutional_id": "a student or employee ID",
        "full_name": "a full name",
        "email": "an email address",
    }
    label = labels.get(field, "the " + field.replace("_", " ") if field else "this field")
    kind, message = issue.get("type", ""), issue.get("msg", "")
    if kind in {"string_too_short", "string_too_long"}:
        length = re.search(r"\b(\d+) characters?\b", message)
        if length:
            limit = "at least" if kind == "string_too_short" else "no more than"
            return f"Please enter {label} with {limit} {length[1]} characters."
    if kind == "missing":
        return f"Please enter {label}."
    if kind in {"enum", "literal_error"}:
        return f"Please choose a valid value for {label}."
    if kind in {"string_type", "string_pattern_mismatch", "int_parsing", "float_parsing"}:
        return f"Please check the format of {label}."
    message = message.removeprefix("Value error, ").replace("String should", "Text should")
    return f"{field.replace('_', ' ').capitalize()}: {message}" if field else message


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
        raise APIError(
            "The backend is unavailable. Run ./run.sh in the project folder and try again."
        ) from error
    if response.status_code == 401 and path != "/auth/login":
        clear_session()
        st.rerun()
    if response.is_error:
        try:
            detail = response.json().get("detail", "Request failed")
            if isinstance(detail, list):
                detail = " ".join(validation_message(issue) for issue in detail)
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
