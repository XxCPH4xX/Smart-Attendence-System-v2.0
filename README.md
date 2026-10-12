# Smart Attendance

A local attendance application for students, teachers, staff and other institutional employees. FastAPI owns authentication, enrollment, attendance rules and reporting. Streamlit provides the administrative interface and a continuous WebRTC camera preview.

The shared daily station marks stable face matches **Present** automatically. Administrators can switch it to staff review. Scheduled class/shift sessions retain staff verification. Face recognition is not a liveness check, and the application does not make disciplinary, grading or payroll decisions.

## Requirements

- Python 3.11; the project and lockfile deliberately exclude Python 3.12+.
- macOS 14+ on Apple Silicon, or a compatible Windows x86-64 / Linux x86-64 computer with a webcam. This development checkout is validated on macOS; the other platforms need hardware integration testing.
- A browser that supports WebRTC and camera permissions.
- Internet access for initial dependency and pretrained model downloads. Routine local use needs no cloud service.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for the reproducible environment.

The pinned FaceNet package requires PyTorch 2.2.x, torchvision 0.17.x, NumPy below 2 and Pillow 10.2. The lockfile resolves those constraints with MediaPipe 0.10.32. PyArrow 19.0.1 preserves compatibility with NumPy 1.26. PyAV 16.0.1 supplies Apple Silicon wheels without a local FFmpeg build. CPU PyTorch wheels are selected on Windows/Linux; CUDA is not required. These are compatibility pins, not a claim that the dependency set is current or suitable for an exposed service.

## Install

Run from the repository root:

```bash
uv python install 3.11
uv sync --locked
uv run attendance init
uv run attendance create-admin
uv run attendance download-models
uv run attendance check-models
```

`attendance init` creates an empty database, applies Alembic migrations and writes a random biometric encryption key to a private `.env` file if one does not exist. It never creates sample people, passwords or attendance records. `create-admin` prompts for credentials without echoing the password. Keep `.env` safe: losing the key makes existing encrypted templates and profile photographs unreadable.

To customize configuration, consult `.env.example` and add variables to the generated `.env`; do not replace its key. SQLite is the default. PostgreSQL uses a URL such as `postgresql+psycopg://user:password@localhost/attendance`; set it before initialization. Restrict database access to the application operator.

Start two terminals:

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

```bash
uv run streamlit run frontend/app.py
```

Open [the dashboard](http://127.0.0.1:8501). The [API reference](http://127.0.0.1:8000/docs) documents individual endpoints and their authentication requirements. Run one API worker: camera tracking and inference are process-local. Daily stations reconnect to the backend after an expired stream or service restart. A browser/device disconnect still requires starting the station again. Login expiry requires signing in again.

On Windows, the same `uv` commands work in PowerShell. On Linux, OpenCV may require distribution packages for `libGL` and `libglib2.0`. macOS users must grant their browser camera access in System Settings → Privacy & Security → Camera. Camera access belongs to the browser, not the backend Python process. For localhost, no TURN server is needed. Remote WebRTC hosting, HTTPS and TURN deployment are outside the local installation.

## Enrollment and attendance

The five main sections are **Home**, **People**, **Take attendance**, **Records** and **Settings**. Advanced administrative tools are grouped under Settings, and optional profile fields and report filters are collapsed.

For a first test, use **Home → Create test profile**. This explicitly creates **Demo Student (DEMO-001)** and uses your existing login. Choose **Add my face**, record permission, then capture or upload three distinct photos. No consent, face images or attendance results are invented. If your face is already enrolled under another person, use that existing profile for testing; duplicate face identities are rejected. Demo records are labelled DEMO-001 in reports and can be deactivated through People when finished.

1. Sign in as the administrator. Under **Settings → Working days & retention**, set institution working days. Add departments, classes, courses and shifts in **Settings → Schedules & organization**.
2. Use **People → Add person** to save a name, ID and person type. Expand **Optional details** when needed. The same ID cannot be registered twice. Student and employee profiles are separate from application login accounts.
3. Record informed consent or an authorized institutional basis. Minors require a guardian authorization reference. Explain retention, revocation and the manual attendance alternative before capture.
4. Upload or capture 3–12 distinct images. Keep one person in each image and vary head angle and lighting slightly. The server rejects poor quality, inconsistent identities and possible duplicate enrollment. Uploaded enrollment images are processed in memory and are not retained. Re-enrollment replaces templates without changing attendance history.
5. Open **Take attendance → Start attendance station** once. All active enrolled people can check in through the same camera; no person selection is needed. New enrollments become available during the running session.
6. Allow browser camera access and keep the page open with the computer awake. The camera keeps running as people approach. Stable matches save the person’s identity, date and check-in time; repeats do not duplicate that day’s station attendance. Unknown, ambiguous, poor-quality and inactive identities are not marked. The next local day starts automatically.
7. Expand **Customize this station** to change its name, processing interval or automatic marking versus staff review. Select the camera in the live preview. Resolution, matching thresholds and image-quality controls are under **Settings → Camera settings**. Changing capture timing requires restarting the station.
8. For scheduled class or shift attendance, create a roster in **Settings → Schedules & organization**, then choose **Class or shift attendance** on the camera screen. Scheduled sessions use their own windows, late rules and reviewed check-ins. Finalize an ended scheduled session to generate missing attendance; the daily station records arrivals only and never generates absences.
9. Use **Records → Attendance history** to filter by dates, category, departments, classes, sections or individual people. CSV, Excel and PDF exports contain reporting metadata and no biometric vectors.

Review or correct records in **Records → Review & correct**. Manual attendance and authorized checkout use the correction form, including a timezone-aware timestamp, reason and conflict check. Every change records its original and updated values. Leave/holiday changes do not silently rewrite existing records.

## Architecture

- `backend/`: SQLAlchemy schema, server-side access checks, opaque hashed login tokens, enrollment lifecycle, attendance transactions, audit records and reporting.
- `vision/`: MediaPipe detector and Face Landmarker, per-face alignment, pretrained 512-dimensional FaceNet inference, matching, temporal stability, bounded camera processing and evaluation.
- `frontend/`: Streamlit pages using the HTTP API. Browser video stays responsive while a single background request performs inference.
- `migrations/`: versioned database migrations.
- `scripts/`: secure initialization, model preparation, recovery, backup and retention commands.
- `notebooks/recognition_evaluation.ipynb`: reproducible experiments on authorized local data, with no saved biometric outputs.

Templates and separately uploaded profile photos use Fernet authenticated encryption. Decryption stays in the backend. Index updates replace a complete immutable snapshot; version changes invalidate cached templates. Expired templates invalidate the snapshot before the next recognition request; an additional refresh runs at least every 30 seconds. Repeated face observations go through the attendance service, which enforces active identity, roster membership, session bounds, exceptions and database uniqueness. Preview work is bounded to one in-flight inference request.

Roles are intentionally conservative: Super Admin manages users, settings and retention-sensitive deletion; Admin manages enrollment and schedules; Staff Operator handles camera and corrections; Teacher and Viewer can inspect institution attendance, with exports restricted to Teacher and administrative roles. This is institution-wide reporting, not class-scoped teacher access. See [operations and privacy](docs/operations.md) before using real records.

## Evaluation

The default cosine method is a provisional baseline, **not a calibrated institutional model**. A score is a similarity, not a probability. Use authorized captures from different sessions for enrollment, validation and test, and genuinely unknown identities in validation/test. The notebook rejects overlapping captures and identical file content, calibrates acceptance on validation only, and compares cosine, KNN and PyNNDescent approximate search on the untouched test split.

Measurements include known accuracy, macro precision/recall/F1, unknown acceptance/rejection, known misidentification, a confusion matrix, matching latency, index build time and Python allocation peak. Matching latency excludes detection/embedding and Python allocation tracking excludes native PyTorch memory; the live panel reports full request processing latency. No recognition accuracy or hardware benchmark is supplied without a dataset. StandardScaler is omitted because it changes the unit-sphere geometry; an MLP is deferred until sufficient authorized data supports a meaningful experiment.

```bash
uv run jupyter notebook notebooks/recognition_evaluation.ipynb
```

## Tests and maintenance

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run alembic check
uv run attendance backup data/backups/attendance.db
uv run attendance purge-expired                 # dry run
uv run attendance purge-expired --apply         # permanent deletion of expired operational records
uv run attendance reset-password               # local administrator recovery
```

Unit/API tests use temporary databases, synthetic embeddings and mocked inference; they never use a real camera or production records. The real model-load check is separate. See [operations](docs/operations.md) for a hardware acceptance checklist and deployment boundaries.

## Limitations and next steps

- No validated presentation-attack detection. Photos or screens may match; automatic station check-ins are labelled `face_matched`, not human-verified. Enable staff review where independent verification is required.
- Face alignment, enrollment quality limits and thresholds require validation under local lighting, pose, demographic variation, occlusion and camera conditions. Attendance must remain contestable.
- No institution-specific accuracy claims, MPS speed claims or cross-platform webcam certification.
- The daily station runs while the browser page stays open, the computer stays awake, and the operator remains signed in. A powered-off camera cannot detect approach without separate sensing hardware. Scheduled class/shift sessions are created explicitly; recurring timetable generation, email password recovery, class-scoped teacher permissions and automatic shift checkout are not implemented.
- The local database includes unencrypted identity and attendance fields; protect the device with full-disk encryption, OS accounts and restricted backups. Audit history retains personal values and needs an approved retention policy.
- Audit records are append-only through the API, but a database administrator can alter them. External tamper-evident storage is not implemented.
- OpenCV overlay text uses ASCII; full Unicode names appear in the dashboard. PDF uses built-in fonts and is best suited to Latin-script reports; use Excel for full Unicode names.
- Disk-backed model files and the locally recorded hash manifest are trusted operator assets. Hash checks detect later changes, not malicious first-download provenance. Never load third-party uploaded pickle/model files.

## References and licenses

This implementation uses the functionality described in the [LinkedIn reference](https://www.linkedin.com/posts/shivakrishnavutukuri04_computervision-facerecognition-machinelearning-ugcPost-7514674406686633984-EAQi/) without copying its code or interface.

[facenet-pytorch](https://github.com/timesler/facenet-pytorch) provides the MIT-licensed InceptionResnetV1 implementation and links to pretrained VGGFace2 weights derived from David Sandberg’s FaceNet work. [MediaPipe](https://github.com/google-ai-edge/mediapipe) is Apache-2.0 licensed; model assets are downloaded from Google’s model distribution. Model weights and training datasets may have separate usage restrictions; verify their terms for the institution's intended deployment. Third-party packages retain their own licenses. Application source is under [MIT](LICENSE).
