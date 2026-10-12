from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select

from backend.api.common import lookup
from backend.auth import (
    audit,
    require,
)
from backend.biometrics import decode_image
from backend.db import get_db, utcnow
from backend.models import (
    AttendanceSession,
    FaceTemplate,
)
from backend.people import get_policy
from backend.schemas import (
    StreamInput,
)
from backend.station import daily_station, enrolled_people

router = APIRouter()


@router.get("/station")
def station_status(request: Request, user=Depends(require("read")), db=Depends(get_db)):
    from zoneinfo import ZoneInfo

    from backend.attendance import session_dict

    now = utcnow()
    day = now.astimezone(ZoneInfo(request.app.state.settings.timezone)).date()
    session = db.scalar(select(AttendanceSession).where(AttendanceSession.station_day == day))
    return {
        "date": day.isoformat(),
        "enrolled_people": db.scalar(
            select(func.count()).select_from(enrolled_people(now).subquery())
        ),
        "session": session_dict(session) if session else None,
    }


@router.post("/station/start", status_code=201)
def start_station(request: Request, user=Depends(require("camera")), db=Depends(get_db)):
    service = request.app.state.vision
    with service.lock:
        service.load()
        session = daily_station(db, user, request.app.state.settings.timezone)
        key = service.create_stream(user, session.id, get_policy(db), station=True)
        audit(db, user, "station_camera_started", "session", session.id)
        db.commit()
    return {"stream_id": key, "session_id": session.id}


@router.get("/vision/status")
def vision_status(request: Request, user=Depends(require("read")), db=Depends(get_db)):
    assets = request.app.state.settings.asset_dir
    return {
        "models_prepared": (assets / "manifest.json").is_file(),
        "model_loaded": request.app.state.vision.detector is not None,
        "active_templates": db.scalar(
            select(func.count()).select_from(FaceTemplate).where(FaceTemplate.expires_at > utcnow())
        ),
        "model": "FaceNet VGGFace2 / MediaPipe alignment v1",
        "method": "cosine",
        "threshold_calibrated": False,
        "anti_spoofing_validated": False,
    }


@router.post("/vision/quality")
def quality_check(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require("enroll")),
    db=Depends(get_db),
):
    service = request.app.state.vision
    image = decode_image(file.file.read(request.app.state.settings.max_upload_bytes + 1))
    with service.lock:
        service.load()
        policy = get_policy(db)
        faces = service.detector.detect(image, policy.min_face_pixels, policy.min_blur_variance)
    return {
        "faces": len(faces),
        "acceptable": len(faces) == 1 and faces[0].quality_ok,
        "feedback": [f.feedback for f in faces],
    }


@router.post("/vision/streams", status_code=201)
def new_stream(
    data: StreamInput, request: Request, user=Depends(require("camera")), db=Depends(get_db)
):
    session = lookup(db, AttendanceSession, data.session_id)
    if session.finalized or not session.starts_at <= utcnow() <= session.cutoff_at:
        raise HTTPException(409, "Select a session with an open check-in window")
    service = request.app.state.vision
    with service.lock:
        service.load()
    key = service.create_stream(user, session.id, get_policy(db))
    audit(db, user, "camera_started", "session", session.id)
    db.commit()
    return {"stream_id": key}


@router.post("/vision/streams/{key}/frame")
async def camera_frame(
    key: str, request: Request, user=Depends(require("camera")), db=Depends(get_db)
):
    from starlette.concurrency import run_in_threadpool

    content = await request.body()
    image = decode_image(content, request.app.state.settings.max_upload_bytes)
    return await run_in_threadpool(request.app.state.vision.process_frame, db, user, key, image)


@router.delete("/vision/streams/{key}", status_code=204)
def stop_camera(key: str, request: Request, user=Depends(require("camera"))):
    request.app.state.vision.stop_stream(user, key)
