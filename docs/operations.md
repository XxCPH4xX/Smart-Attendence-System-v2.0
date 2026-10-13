# Operations and privacy

## Local trust boundary

Run the backend and dashboard on loopback. The dashboard stores an opaque login token in its server-side Streamlit session; only token hashes are persisted in the database. Passwords use Argon2id. Login throttling is database-backed and applied by account and client host. This is a local installation, not a hardened public service: distributed rate limiting, identity federation, reverse-proxy TLS, deployment threat modeling and external audit protection remain deployment work.

All application roles are defined in `backend/auth.py`; each API mutation checks a server-side permission. Face matching never creates a login session. Viewers and teachers cannot operate a camera, enroll identities, change settings or correct records. Teachers can view institution-wide attendance, so institutions requiring class-scoped access must not assign that role until those restrictions are implemented. Never share administrator accounts.

Local password recovery uses `attendance reset-password`. Anyone with access to the database and encryption key can administer the application; OS account controls and full-disk encryption are therefore part of the security boundary. The CLI recovery operation is audited and expires existing login sessions.

## Collection and disputes

Before enrollment, record the purpose, institutional authority or explicit consent, retention period, access roles, manual alternative and revocation contact. For minors, obtain applicable guardian authorization and institution approval. The application records these assertions; it cannot establish legal authority or verify the guardian's identity. Consult the institution's privacy officer about local obligations. This software makes no universal compliance claim.

Do not collect third-party images or use a public dataset as if consent covered institutional attendance. Do not auto-enroll strangers. Enrollment uploads stay in process memory and are not deliberately logged or saved; encrypted templates remain biometric personal data. Profile photos are separately uploaded and encrypted. No continuous footage is recorded.

If attendance is disputed, inspect the attendance record and its verification method, verify using an independent source, and enter a reasoned manual correction. The audit trail retains before/after values. Never infer misconduct from unknown recognition or use automated matching alone for grading, salary or disciplinary decisions.

## Retention and deletion

Revoke biometrics from People → Enroll a face → Enrollment history and removal to remove templates and the profile photo and mark authorization records revoked. Recognition index versioning makes the change visible on the next request. Deactivation also excludes a person from the index and attendance service. Re-enrollment replaces templates atomically without duplicating a person.

Template expiration is assigned when enrolled; changing the setting affects future enrollment. `attendance purge-expired` previews deletion of expired templates, sessions, their records/events/rosters, expired leave records and login sessions. Add `--apply` only after an authorized archive or backup decision. **People → select a person → Delete person** removes a registered person directly, erases face templates and profile photos, and revokes face permission. If attendance, roster or leave history exists, the person's record is retained with check-in access disabled; otherwise the profile is deleted. Deletion is audited with an automatic reason and requires no extra form. The same action is available for a selected person in Records. Retained profiles are available under **More filters → Removed people** and can be restored with **Restore person**; camera attendance then requires fresh permission and enrollment. A manual correction for a removed person currently requires restoring the person, correcting the record, then removing them again; all steps are audited.

Authorization/enrollment history and audit logs do not have automatic deletion because their evidentiary retention requirements may differ from attendance. They can include names and reasons in profile-change snapshots. Define a separate institution-approved retention process, including backups; biometric revocation does not erase historical audit values. A database operator must perform any approved audit erasure outside the application and retain evidence of that authorization.

## Backup and restore

For SQLite, run `uv run attendance backup data/backups/attendance.db`. The online SQLite backup API takes a consistent snapshot, including WAL changes. The destination is created with owner-only permissions and must not already exist. It includes identity and attendance data; secure the directory. Back up `.env` separately using an encrypted secret store. Test restoration on a separate local directory with the same encryption key.

Stop both services before replacing the active SQLite database. Copy the backup into place; remove obsolete `-wal` and `-shm` files only after confirming no process has the database open. Run `uv run alembic upgrade head` and test login and authorized enrollment access. Never commit database or model assets.

For PostgreSQL, use PostgreSQL's `pg_dump`/`pg_restore` tooling and a restricted service account. Restore into a new database and run migrations before redirecting the application URL. SQLite tests do not certify PostgreSQL behavior; run the suite and concurrent attendance checks against your configured PostgreSQL instance before deployment.

## Model assets and upgrades

The downloader uses fixed official release URLs, writes to temporary files, then records SHA-256 hashes and atomically renames each asset. Subsequent downloads refuse a changed checksum; investigate upstream before replacing a manifest. Inference checks all hashes before opening model files. FaceNet loads only the trusted local file with PyTorch's weights-only option. The package requires an older PyTorch release; do not treat that option as a security sandbox or accept user-supplied model weights. Update dependencies and reassess security advisories before exposing this service beyond localhost.

Model changes require a new embedding version and re-enrollment; embeddings from different models/alignment conventions cannot be compared blindly. Recognition threshold changes need validation and a recorded operational decision. The default method remains cosine; the notebook compares alternative indexes rather than silently promoting them.

## Hardware acceptance

Automated tests intentionally do not access a webcam or record people. With authorized participants:

1. Log in, register each category and verify permission boundaries with a restricted account.
2. Enroll at least three distinct images, including mild lighting/pose changes; verify multi-face and blurred samples are rejected.
3. Start a current session with an explicit roster and camera permission. Check a known face, an unknown person and multiple people in view. Verify labels follow boxes and the camera stays responsive.
4. Hold a known face in view for repeated observations. In daily station mode, confirm one Present record per person per local day and no duplicate on subsequent frames or a station restart. Enable staff review and confirm pending check-ins need approval. For scheduled sessions, approve a pending record and confirm the grace/late rule.
5. Stop the camera, deny permission, disconnect the camera and stop the backend independently. Confirm feedback, resource release and recovery by starting a fresh stream.
6. Re-enroll, revoke consent and deactivate a person while recognition is open; verify the next frames reflect the change.
7. Test manual attendance, checkout-enabled/disabled sessions, end-of-session finalization, holidays, leave and disputed attendance corrections.
8. Export real test-session records to CSV/Excel/PDF and inspect names, filters and dates. Use Excel for scripts unsupported by the PDF font.
9. Evaluate independent captures and unknown identities before approving any threshold. Keep diagnostic data under the same controls as enrollment data.

## Troubleshooting

- **No camera:** close other camera applications; allow camera use in both the browser and OS settings. Use `localhost`, not an insecure LAN URL. A desktop camera test cannot run in a headless environment.
- **Models unavailable:** run `attendance download-models`, then `attendance check-models`. Do not copy arbitrary weights into the assets directory.
- **Slow inference:** use CPU first, reduce processing width or increase the interval. MPS is optional through `ATTENDANCE_DEVICE=mps`; restart and measure it locally. Preview frames do not queue behind model inference.
- **Recognition expired:** daily stations reconnect automatically after an expired backend stream. For browser/device disconnections, use Stop attendance station and Start attendance station. Idle server streams expire after two minutes; missing observations reset identity stability.
- **Enrollment rejects a face:** use a larger, sharper, evenly lit face. Verify only one face is present and that the samples show the same person. Duplicate matching requires staff review, not an automatic override.
- **Dependency errors:** use Python 3.11 and `uv sync --locked`; do not independently upgrade torch, torchvision, NumPy or Pillow. PyAV wheels require macOS 14 on Apple Silicon with the selected version.
- **Database not initialized:** run `attendance init` before starting the dashboard. Existing databases are migrated without adding demonstration data.
