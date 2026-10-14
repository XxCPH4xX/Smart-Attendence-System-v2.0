# Smart Attendance

A local attendance application for students, teachers, staff and other institutional employees. FastAPI owns authentication, enrollment, attendance rules and reporting. Streamlit provides the administrative interface and a continuous WebRTC camera preview.

The shared daily station marks stable face matches **Present** automatically. Administrators can switch it to staff review. Scheduled class/shift sessions retain staff verification. Face recognition is not a liveness check, and the application does not make disciplinary, grading or payroll decisions.

## Requirements

- Python 3.11. Python 3.12+ is not supported by the pinned dependencies.
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

After installation, start the app with one command:

```bash
./run.sh
```

The launcher starts the backend and dashboard together. Keep the terminal open and press **Ctrl+C** to stop both. If a service is already running, it is reused and left running when the launcher exits. On Windows, use `uv run python -m scripts.run_local` instead.

Open [the dashboard](http://127.0.0.1:8501). The [API reference](http://127.0.0.1:8000/docs) documents individual endpoints and their authentication requirements. Run one API worker: camera tracking and inference are process-local. After an attendance reset, expired stream, backend restart or browser/device disconnect, start the station again. This prevents an unattended reconnect from recreating cleared check-ins. Login expiry requires signing in again.

Sign-in survives page refreshes through an HttpOnly browser cookie and the existing server session. Sessions expire after eight hours by default (`ATTENDANCE_SESSION_HOURS`); refreshing does not extend them. Sign out from the account menu on a shared computer. Sign-out, password changes and account disabling revoke access. Cookies must be allowed. The local launcher configures the matching backend/dashboard origins automatically, including custom ports.

The installation commands also work in PowerShell on Windows. On Linux, OpenCV may require distribution packages for `libGL` and `libglib2.0`. macOS users must grant their browser camera access in System Settings → Privacy & Security → Camera. Camera access belongs to the browser, not the backend Python process. For localhost, no TURN server is needed. Remote WebRTC hosting, HTTPS and TURN deployment are outside the local installation.

## Workspace and daily use

The workspace is grouped into **Overview**, **Live Recognition**, **Students**, **Teachers**, **Staff**, **Enrollment**, **Attendance Operations**, **Reports & Analytics**, **Administration** and **System Settings**. Controls are shown according to the signed-in account's permissions. Category directories, attendance calendars, profiles, reports, exports, rosters and leave history are scoped by backend queries.

1. Set the institution name and timezone in **Administration → Institution**. Configure working days under **System Settings → Attendance policies**. Existing sessions keep their original timezone.
2. Add departments and classes under **Students → Classes & sections**, teaching courses under **Teachers → Departments & courses**, and staff shifts under **Staff → Departments & shifts**.
3. Choose **Register a person** on Overview or in a directory. The five-step wizard collects category, personal information, institutional details, attendance method and final review. Age determines guardian authorization requirements. Choose **Other** for a custom type such as Contractor. Nothing is saved until **Confirm registration**; person, authorization and face templates commit together or roll back together. Choosing manual attendance explicitly creates a profile without biometrics.
4. For face enrollment, record informed permission or institutional authorization, including a guardian reference for minors. Capture or upload 3–12 distinct face photos. The compact preview has **Use photo** and **Retake** controls. Every selected photo can be removed or retaken. Poor-quality images, inconsistent identities and possible duplicate enrollment are rejected by the backend. Enrollment images are processed in memory and are not retained.
5. Start **Live Recognition → Start attendance station**. Active enrolled people use one shared camera; no individual selection is needed. Stable matches save identity, date and check-in time. Repeated observations do not duplicate daily station attendance. Unknown or ambiguous faces are never registered automatically. The next local day starts automatically while the station is running.
6. Keep the page open, the computer awake and the browser authorized to use the camera. **Refresh camera** creates a fresh stream. Camera selection is in the preview controls; processing settings are under **System Settings**. Stop/restart recognition after timing or capture changes.
7. For scheduled class or shift attendance, create a session and explicit roster in **Attendance Operations → Active sessions**, or the category's schedule section. Select that session in Live Recognition. Scheduled check-ins require review and use their own time windows and late rules. Finalize ended sessions to record missing roster attendance; the shared daily station records arrivals only and does not infer absences.
8. Review pending check-ins, enter manual attendance, correct times or record authorized checkout in **Attendance Operations**. Corrections require reasons and reject concurrent edits. Leave/holiday changes do not rewrite existing attendance.
9. Filter history or export CSV, Excel or PDF in **Reports & Analytics**. Category modules and individual profiles have scoped attendance views and calendars. The Overview counts each person once per day; late takes precedence over on-time attendance if different sessions have different states. Report rates count recorded session entries, excluding pending, leave, excused and holiday states.

For a disposable test profile, use **Enrollment → Enrollment management → Test face recognition**. This creates **Demo Student (DEMO-001)** under the existing login. Enroll your own face with permission; a face already registered under another profile cannot be duplicated. Profiles are separate from application login accounts.

## Reset, remove and recover

**Clear filters**, **Reset form**, **Discard draft** and **Reset unsaved settings** affect unsaved controls only. **Reports & Analytics → Reset attendance** clears attendance matching the selected dates and filters. **Live Recognition → Reset today's attendance** clears the daily station; a scheduled session has its own reset. Each history row has a **Delete record** action. Destructive actions show a confirmation dialog.

Attendance deletion is available to Admin and Super Admin, stops affected cameras and preserves registered people and saved faces. Counters and report rates recalculate from saved records and show zero when cleared. Registered-profile counts stay unchanged after attendance reset and decrease when a person is removed. **Undo last attendance reset or deletion**, or **Recently deleted attendance**, restores a deleted group for 30 days without overwriting a new record for the same person and session. Deletions and recovery are audited.

Each entry in **Attendance Operations → Active sessions** has **Reset attendance** and **Remove session** actions for authorized administrators. Reset clears only that session's attendance and keeps its schedule and roster. Remove stops its camera and hides the session while preserving attendance in Reports. Use **Show removed sessions → Restore session** to bring it back. Removing a daily station does not immediately create another; starting recognition creates a fresh station for that day. An older daily station cannot be restored while another active station exists for the same date.

A directory's **Actions → Delete person** removes someone directly after confirmation; prior deactivation is not required. It erases face data and retains past attendance. Retained profiles appear under **Status → Paused / removed**. **Restore check-ins** restores access; erased face data requires fresh enrollment. **Pause check-ins** is reversible and keeps saved face templates.

## Architecture

- `backend/`: SQLAlchemy schema, server-side access checks, opaque hashed login tokens, enrollment lifecycle, attendance transactions, audit records and reporting.
- `vision/`: MediaPipe detector and Face Landmarker, per-face alignment, pretrained 512-dimensional FaceNet inference, matching, temporal stability, bounded camera processing and evaluation.
- `frontend/`: shared design, navigation, category workspaces, an atomic registration wizard and Streamlit views using the HTTP API. Browser video stays responsive while a single background request performs inference.
- `migrations/`: versioned database migrations.
- `scripts/`: secure initialization, model preparation, recovery, backup and retention commands.
- `notebooks/recognition_evaluation.ipynb`: reproducible experiments on authorized local data, with no saved biometric outputs.

Templates and separately uploaded profile photos use Fernet authenticated encryption. Decryption stays in the backend. Index updates replace a complete immutable snapshot; version changes invalidate cached templates. Expired templates invalidate the snapshot before the next recognition request; an additional refresh runs at least every 30 seconds. Repeated face observations go through the attendance service, which enforces active identity, roster membership, session bounds, exceptions and database uniqueness. Preview work is bounded to one in-flight inference request.

Roles are intentionally conservative: Super Admin manages users, settings and retention-sensitive deletion; Admin manages enrollment and schedules; Staff Operator handles camera and corrections; Teacher and Viewer can inspect institution attendance, with exports restricted to Teacher and administrative roles. This is institution-wide reporting, not class-scoped teacher access. The [workspace design notes](docs/workspace-design.md) record the audit, architecture decision and data semantics. See [operations and privacy](docs/operations.md) before using real records.

## Evaluation

The default cosine threshold requires local calibration. Scores represent similarity, not probability. Use authorized captures from separate sessions for enrollment, validation and test, with unenrolled identities in validation and test. The notebook rejects overlapping captures and duplicate images, calibrates thresholds on validation data, and compares cosine, KNN and PyNNDescent search on the held-out test split.

Measurements include known accuracy, macro precision/recall/F1, unknown acceptance/rejection, known misidentification, a confusion matrix, matching latency, index build time and peak Python allocation. Matching latency excludes detection and embedding; Python allocation tracking excludes native PyTorch memory. Frame API responses include server processing time as `latency_ms`. Run the notebook on an authorized dataset to obtain recognition metrics and benchmarks.

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

Related demonstration: [face recognition attendance](https://www.linkedin.com/posts/shivakrishnavutukuri04_computervision-facerecognition-machinelearning-ugcPost-7514674406686633984-EAQi/).

[facenet-pytorch](https://github.com/timesler/facenet-pytorch) provides the MIT-licensed InceptionResnetV1 implementation and links to pretrained VGGFace2 weights derived from David Sandberg’s FaceNet work. [MediaPipe](https://github.com/google-ai-edge/mediapipe) is Apache-2.0 licensed; model assets are downloaded from Google’s model distribution. Model weights and training datasets may have separate usage restrictions; verify their terms for the institution's intended deployment. Third-party packages retain their own licenses. Application source is under [MIT](LICENSE).
