import argparse
import getpass
import hashlib
import json
import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from urllib.request import urlopen

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import delete, select

from backend.auth import audit, hasher
from backend.config import get_settings
from backend.db import make_engine, session_factory, utcnow
from backend.models import (
    AttendanceRecord,
    AttendanceSession,
    FaceTemplate,
    Leave,
    LoginSession,
    Policy,
    SessionMember,
    User,
)
from backend.people import bump_index
from backend.schemas import PolicyInput, UserInput

ASSETS = {
    "blaze_face_short_range.tflite": "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "20180402-114759-vggface2.pt": "https://github.com/timesler/facenet-pytorch/releases/download/v2.2.9/20180402-114759-vggface2.pt",
}


def initialize():
    Path("data").mkdir(mode=0o700, exist_ok=True)
    env = Path(".env")
    if not env.exists():
        key = Fernet.generate_key().decode()
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(f"ATTENDANCE_BIOMETRIC_KEY={key}\nATTENDANCE_TIMEZONE=Asia/Dhaka\n")
    settings = get_settings()
    try:
        Fernet(settings.biometric_key.encode())
    except ValueError as error:
        raise SystemExit(
            "Set ATTENDANCE_BIOMETRIC_KEY to a Fernet key in .env; do not replace an existing key."
        ) from error
    command.upgrade(Config("alembic.ini"), "head")
    engine = make_engine(settings.database_url)
    with session_factory(engine)() as db:
        if not db.get(Policy, 1):
            db.add(Policy(id=1, values=PolicyInput().model_dump(), index_version=0))
            db.commit()
    engine.dispose()
    print(
        "Database migrated. Encryption key is stored in .env; back it up separately and securely."
    )


def account(reset=False):
    settings = get_settings()
    username = input("Username: ").strip()
    password = getpass.getpass("New password (at least 12 characters): ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords did not match")
    try:
        validated = UserInput(username=username, password=password, role="super_admin")
    except ValidationError as error:
        messages = [
            f"{issue['loc'][0]}: {issue['msg']}"
            for issue in error.errors(include_input=False, include_context=False)
        ]
        raise SystemExit("Account was not saved. " + "; ".join(messages)) from None
    engine = make_engine(settings.database_url)
    with session_factory(engine)() as db:
        user = db.scalar(select(User).where(User.username == username))
        if reset:
            if not user:
                raise SystemExit("User not found")
            user.password_hash = hasher.hash(validated.password)
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            audit(
                db,
                None,
                "local_password_recovery",
                "user",
                user.id,
                reason="Recovery performed by local system administrator",
            )
        else:
            if user:
                raise SystemExit("Username already exists")
            if db.scalar(select(User.id).where(User.role == "super_admin", User.active.is_(True))):
                raise SystemExit(
                    "An administrator already exists; create further accounts from User Management"
                )
            user = User(
                username=validated.username,
                password_hash=hasher.hash(validated.password),
                role="super_admin",
            )
            db.add(user)
            db.flush()
            audit(db, None, "initial_admin_created", "user", user.id)
        db.commit()
    engine.dispose()
    print("Account updated." if reset else "Initial administrator created.")


def download_models():
    directory = get_settings().asset_dir
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, url in ASSETS.items():
        destination = directory / name
        if (
            destination.exists()
            and manifest.get(name) == hashlib.sha256(destination.read_bytes()).hexdigest()
        ):
            print(f"Verified {name}")
            continue
        temporary = destination.with_suffix(destination.suffix + ".part")
        print(f"Downloading {name}")
        try:
            with urlopen(url, timeout=120) as source, temporary.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            if name in manifest and digest != manifest[name]:
                raise RuntimeError(f"Checksum changed for {name}; inspect the upstream release")
            temporary.replace(destination)
            manifest[name] = digest
            temp_manifest = manifest_path.with_suffix(".tmp")
            temp_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
            temp_manifest.replace(manifest_path)
        finally:
            temporary.unlink(missing_ok=True)
    print("Model assets prepared. Checksums will be checked before inference.")


def backup(destination):
    settings = get_settings()
    if not settings.database_url.startswith("sqlite:///"):
        raise SystemExit("Use pg_dump for PostgreSQL; see docs/operations.md")
    path = Path(destination)
    if path.exists():
        raise SystemExit("Backup destination already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(settings.database_url.removeprefix("sqlite:///")) as source:
        with sqlite3.connect(path) as target:
            source.backup(target)
    print(
        f"Backup saved to {path}. It contains personal data; protect it and store .env separately."
    )


def retention(apply=False):
    settings = get_settings()
    engine = make_engine(settings.database_url)
    with session_factory(engine)() as db:
        policy = PolicyInput(**db.get(Policy, 1).values)
        now = utcnow()
        cutoff = now - timedelta(days=policy.attendance_retention_days)
        templates = list(db.scalars(select(FaceTemplate.id).where(FaceTemplate.expires_at < now)))
        sessions = list(
            db.scalars(select(AttendanceSession.id).where(AttendanceSession.ends_at < cutoff))
        )
        leaves = list(db.scalars(select(Leave.id).where(Leave.ends_on < cutoff.date())))
        print(
            f"Expired: {len(templates)} templates, {len(sessions)} sessions, {len(leaves)} leave records."
        )
        if not apply:
            print("Dry run. Use purge-expired --apply to delete these records permanently.")
            return
        db.execute(delete(FaceTemplate).where(FaceTemplate.id.in_(templates)))
        # Event rows cascade when their attendance record is deleted.
        db.execute(delete(AttendanceRecord).where(AttendanceRecord.session_id.in_(sessions)))
        db.execute(delete(SessionMember).where(SessionMember.session_id.in_(sessions)))
        db.execute(delete(AttendanceSession).where(AttendanceSession.id.in_(sessions)))
        db.execute(delete(Leave).where(Leave.id.in_(leaves)))
        db.execute(delete(LoginSession).where(LoginSession.expires_at < now))
        bump_index(db)
        audit(
            db,
            None,
            "retention_purge",
            "database",
            "retention",
            after={"templates": len(templates), "sessions": len(sessions), "leaves": len(leaves)},
        )
        db.commit()
    engine.dispose()
    print("Expired operational records removed; audit and consent history remain retained.")


def main():
    parser = argparse.ArgumentParser(description="Smart Attendance maintenance")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ["init", "create-admin", "reset-password", "download-models", "check-models"]:
        sub.add_parser(name)
    sub.add_parser("backup").add_argument("destination")
    sub.add_parser("purge-expired").add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.action == "init":
        initialize()
    elif args.action in {"create-admin", "reset-password"}:
        account(args.action == "reset-password")
    elif args.action == "download-models":
        download_models()
    elif args.action == "check-models":
        from backend.biometrics import VisionService

        service = VisionService(get_settings())
        import numpy as np

        try:
            service.load()
            if service.detector.detect(np.zeros((480, 640, 3), np.uint8)):
                raise RuntimeError("A blank frame produced an unexpected face detection")
            vectors = service.embedder.extract([np.full((160, 160, 3), 128, np.uint8)] * 2)
            if vectors.shape != (2, 512) or not np.allclose(
                np.linalg.norm(vectors, axis=1), 1, atol=1e-5
            ):
                raise RuntimeError("Embedding shape or normalization check failed")
        finally:
            service.close()
        print("Models loaded; blank-frame detection and batched embedding inference passed.")
    elif args.action == "backup":
        backup(args.destination)
    elif args.action == "purge-expired":
        retention(args.apply)


if __name__ == "__main__":
    main()
