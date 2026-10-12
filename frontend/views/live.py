from datetime import datetime

import streamlit as st
from streamlit_webrtc import WebRtcMode, webrtc_streamer

from backend.config import get_settings
from backend.db import utcnow
from frontend.client import request
from vision.camera import RemoteProcessor


def render():
    st.caption("Continuous camera preview · CPU-friendly recognition · Staff verification required")
    now = utcnow()
    sessions = {
        s["id"]: s
        for s in request("GET", "/sessions")
        if not s["finalized"]
        and datetime.fromisoformat(s["starts_at"]) <= now <= datetime.fromisoformat(s["cutoff_at"])
    }
    if not sessions:
        st.info(
            "There is no open check-in session. Create a session and assign its roster in Sessions & Schedules."
        )
        return
    selected = st.selectbox(
        "Active attendance session",
        list(sessions),
        format_func=lambda i: f"#{i} · {sessions[i]['name']}",
        disabled=bool(st.session_state.get("stream_id")),
    )
    policy = request("GET", "/settings")["policy"]
    if not st.session_state.get("stream_id"):
        if st.button("Prepare camera", type="primary"):
            result = request("POST", "/vision/streams", json={"session_id": selected})
            st.session_state.stream_id = result["stream_id"]
            st.rerun()
        st.caption(
            "After preparing, use START on the video panel and allow browser camera access. No continuous video is recorded."
        )
        return
    if st.button("Release camera session"):
        if st.session_state.get("processor"):
            st.session_state.processor.close()
            del st.session_state.processor
        else:
            request("DELETE", f"/vision/streams/{st.session_state.stream_id}")
        del st.session_state.stream_id
        st.rerun()
    main, side = st.columns([3, 1])
    with main:
        stream_id = st.session_state.stream_id
        token = st.session_state.token

        def factory():
            return RemoteProcessor(
                get_settings().api_url,
                token,
                stream_id,
                policy["processing_interval"],
                policy["processing_width"],
            )

        context = webrtc_streamer(
            key=f"camera-{stream_id}",
            mode=WebRtcMode.SENDRECV,
            rtc_configuration={"iceServers": []},
            media_stream_constraints={
                "video": {"width": {"ideal": 640}, "height": {"ideal": 480}},
                "audio": False,
            },
            video_processor_factory=factory,
            async_processing=False,
        )
        if context.video_processor:
            st.session_state.processor = context.video_processor
        if not context.state.playing and st.session_state.get("was_playing"):
            if st.session_state.get("processor"):
                st.session_state.processor.close()
                del st.session_state.processor
            st.session_state.pop("stream_id", None)
            st.session_state.was_playing = False
            st.rerun()
        st.session_state.was_playing = context.state.playing
    with side:

        @st.fragment(run_every=1)
        def feedback():
            processor = st.session_state.get("processor")
            if not processor:
                st.info("Use START to open the browser camera.")
                return
            result = processor.snapshot()
            st.metric("Last inference", f"{result.get('latency_ms', 0):.0f} ms")
            if result.get("error"):
                st.error(result["error"])
            for face in result.get("faces", []):
                st.write(f"**{face['name']}**")
                st.caption(face["label"])
                st.write(face["feedback"])
                if face.get("similarity") is not None:
                    st.caption(f"Cosine similarity: {face['similarity']:.3f}")

        feedback()
    st.subheader("Recent attendance in this session")

    @st.fragment(run_every=5)
    def recent():
        day = sessions[selected]["local_date"]
        rows = request("GET", "/attendance", params={"start": day, "end": day})
        st.dataframe(
            [r for r in rows if r["session_id"] == selected],
            hide_index=True,
            use_container_width=True,
        )

    recent()
