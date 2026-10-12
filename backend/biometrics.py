import hashlib
import json
import secrets
import threading
import time
from datetime import timedelta
from io import BytesIO

import numpy as np
from cryptography.fernet import Fernet
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.attendance import recognized_checkin
from backend.auth import audit
from backend.db import utcnow
from backend.models import Consent, Enrollment, FaceTemplate, Person, Policy
from backend.people import bump_index, get_policy
from vision.recognition import RecognitionIndex, normalize
from vision.tracking import StabilityTracker

MODEL_VERSION = "facenet-vggface2-mp-align-v1"


def cipher(settings):
    try:
        return Fernet(settings.biometric_key.encode())
    except (ValueError, TypeError) as error:
        raise HTTPException(
            503, "Biometric key is missing or invalid. Run attendance init."
        ) from error


def decode_image(content, maximum=8_000_000):
    if len(content) > maximum:
        raise HTTPException(413, "Image exceeds the upload limit")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.width * image.height > 12_000_000 or min(image.size) < 64:
                raise HTTPException(422, "Image must contain 64 pixels per side and at most 12 MP")
            image.load()
            rgb = np.asarray(image.convert("RGB"))
        return np.ascontiguousarray(rgb)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise HTTPException(422, "Invalid image") from error


class VisionService:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.stream_lock = threading.Lock()
        self.detector = self.embedder = None
        self.index = RecognitionIndex([], [], -1)
        self.index_loaded_at = 0
        self.index_expires_at = None
        self.streams = {}

    def load(self):
        if self.detector is not None:
            return
        from vision.detection import FaceDetector
        from vision.embeddings import Embedder

        manifest_path = self.settings.asset_dir / "manifest.json"
        if not manifest_path.exists():
            raise HTTPException(503, "Models are not prepared. Run attendance download-models.")
        manifest = json.loads(manifest_path.read_text())
        for name in (
            "blaze_face_short_range.tflite",
            "face_landmarker.task",
            "20180402-114759-vggface2.pt",
        ):
            path = self.settings.asset_dir / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get(
                name
            ):
                raise HTTPException(503, "Model integrity check failed; download the models again")
        try:
            embedder = Embedder(self.settings.asset_dir, self.settings.device)
            detector = FaceDetector(self.settings.asset_dir)
            self.embedder, self.detector = embedder, detector
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    def refresh(self, db):
        version = db.get(Policy, 1).index_version
        if (
            version == self.index.version
            and time.monotonic() - self.index_loaded_at < 30
            and (self.index_expires_at is None or self.index_expires_at > utcnow())
        ):
            return
        encryption = cipher(self.settings)
        templates = db.execute(
            select(FaceTemplate, Person.id)
            .join(Person, Person.id == FaceTemplate.person_id)
            .join(Enrollment, Enrollment.id == FaceTemplate.enrollment_id)
            .join(Consent, Consent.id == Enrollment.consent_id)
            .where(
                Person.active.is_(True),
                FaceTemplate.expires_at > utcnow(),
                FaceTemplate.model_version == MODEL_VERSION,
                Consent.revoked_at.is_(None),
            )
        ).all()
        vectors, labels = [], []
        for template, person_id in templates:
            vector = np.frombuffer(
                encryption.decrypt(template.encrypted_vector), dtype="<f4"
            ).copy()
            vectors.append(vector)
            labels.append(person_id)
        self.index = RecognitionIndex(vectors, labels, version)
        self.index_loaded_at = time.monotonic()
        self.index_expires_at = min(
            (template.expires_at for template, _ in templates), default=None
        )

    def analyze(self, db, rgb):
        self.load()
        self.refresh(db)
        policy = get_policy(db)
        faces = self.detector.detect(rgb, policy.min_face_pixels, policy.min_blur_variance)
        valid = [face for face in faces if face.quality_ok]
        embeddings = iter(self.embedder.extract([face.crop for face in valid]))
        results = []
        for face in faces:
            result = {
                "box": face.box,
                "person_id": None,
                "name": "Unknown",
                "label": "Identity not verified",
                "feedback": face.feedback,
                "status": "low_quality",
                "similarity": None,
            }
            if face.quality_ok:
                match = self.index.match(
                    next(embeddings), policy.similarity_threshold, policy.ambiguity_margin
                )
                result.update(status=match.status, similarity=round(match.similarity, 4))
                if match.person_id:
                    person = db.get(Person, match.person_id)
                    if person and person.active:
                        result.update(
                            person_id=person.id,
                            name=person.full_name,
                            label=f"{person.category.title()} | {person.institutional_id}",
                            feedback="Recognized; waiting for stable observations",
                        )
                else:
                    result["feedback"] = (
                        "Ambiguous match" if match.status == "ambiguous" else "Unknown"
                    )
            results.append(result)
        return results

    def enroll(self, db, user, person_id, consent_id, images):
        person = db.scalar(select(Person).where(Person.id == person_id).with_for_update())
        consent = db.get(Consent, consent_id)
        if not person or not person.active:
            raise HTTPException(409, "Person is inactive or unavailable")
        if not consent or consent.person_id != person_id or consent.revoked_at:
            raise HTTPException(422, "Current enrollment authorization is required")
        if person.is_minor and not consent.guardian:
            raise HTTPException(422, "Guardian authorization is required for a minor")
        if not 3 <= len(images) <= 12:
            raise HTTPException(422, "Provide between 3 and 12 distinct face samples")
        if len({hashlib.sha256(image).digest() for image in images}) != len(images):
            raise HTTPException(422, "Repeated images are not valid enrollment samples")
        with self.lock:
            self.load()
            self.refresh(db)
            policy = get_policy(db)
            crops = []
            for i, image in enumerate(images, 1):
                faces = self.detector.detect(
                    decode_image(image), policy.min_face_pixels, policy.min_blur_variance
                )
                if len(faces) != 1 or not faces[0].quality_ok:
                    feedback = (
                        faces[0].feedback if len(faces) == 1 else "Exactly one face is required"
                    )
                    raise HTTPException(422, f"Sample {i}: {feedback}")
                crops.append(faces[0].crop)
            vectors = normalize(self.embedder.extract(crops))
            coherence = vectors @ vectors.T
            if np.min(coherence) < 0.6:
                raise HTTPException(
                    422, "Samples are inconsistent; capture the same person clearly"
                )
            others = self.index.labels != person_id
            if (
                others.any()
                and float((vectors @ self.index.vectors[others].T).max())
                >= policy.similarity_threshold
            ):
                raise HTTPException(409, "Possible duplicate identity; review existing enrollment")
            encryption = cipher(self.settings)
            enrollment = Enrollment(
                person_id=person_id,
                consent_id=consent_id,
                recorded_by=user.id,
                sample_count=len(vectors),
            )
            db.add(enrollment)
            db.flush()
            db.execute(delete(FaceTemplate).where(FaceTemplate.person_id == person_id))
            for vector in vectors:
                db.add(
                    FaceTemplate(
                        person_id=person_id,
                        enrollment_id=enrollment.id,
                        encrypted_vector=encryption.encrypt(vector.astype("<f4").tobytes()),
                        model_version=MODEL_VERSION,
                        expires_at=utcnow() + timedelta(days=policy.template_retention_days),
                    )
                )
            bump_index(db)
            audit(
                db,
                user,
                "face_enrolled",
                "person",
                person_id,
                after={"samples": len(vectors), "enrollment_id": enrollment.id},
            )
            db.commit()
            self.refresh(db)
            return {
                "enrollment_id": enrollment.id,
                "samples": len(vectors),
                "index_version": self.index.version,
            }

    def create_stream(self, user, session_id, policy):
        with self.stream_lock:
            now = time.monotonic()
            self.streams = {k: v for k, v in self.streams.items() if now - v["last_seen"] < 120}
            owned = [key for key, value in self.streams.items() if value["user_id"] == user.id]
            for key in owned:
                del self.streams[key]
            if len(self.streams) >= 8:
                raise HTTPException(429, "All camera processing slots are in use")
            key = secrets.token_urlsafe(24)
            self.streams[key] = {
                "user_id": user.id,
                "session_id": session_id,
                "last_seen": now,
                "last_frame": 0,
                "tracker": StabilityTracker(policy.stable_observations, policy.stable_seconds),
            }
            return key

    def process_frame(self, db, user, key, rgb):
        started = time.monotonic()
        with self.lock:
            with self.stream_lock:
                stream = self.streams.get(key)
                if (
                    not stream
                    or stream["user_id"] != user.id
                    or started - stream["last_seen"] > 120
                ):
                    raise HTTPException(404, "Camera session expired. Start the camera again.")
                policy = get_policy(db)
                if started - stream["last_frame"] < policy.processing_interval * 0.8:
                    raise HTTPException(429, "Frame processing rate exceeded")
                stream["last_seen"] = stream["last_frame"] = started
            faces = self.analyze(db, rgb)
            flags = stream["tracker"].update([(f["box"], f["person_id"]) for f in faces], started)
            for face, stable in zip(faces, flags, strict=True):
                face["stable"] = stable
                if not stable:
                    continue
                try:
                    record, feedback = recognized_checkin(
                        db,
                        user,
                        stream["session_id"],
                        face["person_id"],
                        f"{key}:{face['person_id']}",
                    )
                    face.update(
                        feedback=feedback, record_id=record.id, attendance_status=record.status
                    )
                except HTTPException as error:
                    face["feedback"] = str(error.detail)
                except IntegrityError:
                    db.rollback()
                    face["feedback"] = "Attendance was already recorded; refresh attendance history"
            return {
                "faces": faces,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "index_version": self.index.version,
                "error": None,
            }

    def stop_stream(self, user, key):
        with self.stream_lock:
            if key in self.streams and self.streams[key]["user_id"] == user.id:
                del self.streams[key]

    def close(self):
        with self.lock:
            if self.detector:
                self.detector.close()
            self.detector = self.embedder = None
            self.streams.clear()
