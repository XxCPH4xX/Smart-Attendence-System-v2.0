# Institutional workspace

## Audit and architecture decision

The audit covered API routes, authentication and permissions, schema relationships, attendance transactions, reporting, template encryption, recognition/tracking, the local launcher, migrations and the Streamlit interface. Existing constraints already protect unique institutional IDs, explicit rosters, one attendance record per person/session, concurrent corrections and template authorization. The redesign preserves those services.

The main problems were mixed-category pages, incomplete registration saved before face validation, controls grouped under unrelated settings, ambiguous reset labels, limited dashboard navigation and stale widget state between workflows. Category views now pass mandatory category filters to backend queries; combined reporting remains an explicitly institution-wide workspace. This is data scoping, not a new tenant or class-based authorization model.

Streamlit remains the frontend. Its existing WebRTC bridge, authenticated server session, fragments, dialogs and form controls support the local application's workflows without a second frontend or duplicated recognition logic. Shared design and navigation modules replace page-specific styling and the old mixed-person form. React would be appropriate for a separately planned public, multi-tenant application with finer client-side navigation, a kiosk service and stronger browser state management; it would not remove those backend requirements.

## Data and workflow decisions

- Registration uses a single multipart endpoint and transaction. Personal details, authorization and encrypted face templates either commit together or roll back. Manual registration is an explicit alternative. Drafts and selected images stay in the application's session memory until saved or discarded.
- Students, teachers, staff and other roles share the identity table with a validated category. Category-specific form fields, filters, schedules, leave, profiles and exports are enforced by scoped queries. Assigned teaching courses only apply to teachers.
- Overview totals count active registered profiles. Daily attendance charts count unique person/day pairs, prioritizing late over present over pending over absent. Finalized session absences are not inferred from a lack of camera observations. Reports count actual session records and explain their denominator.
- The institution name/timezone use the existing versioned policy JSON. Existing sessions retain their original timezone. Migrations through `0004` add custom types, age, recoverable attendance deletion and session removal. Removed sessions keep their roster and attendance; a partial unique index allows a new active daily station without changing the old session's history.
- Reset attendance clears the selected attendance scope, stops affected recognition streams and preserves profiles/templates. A reset is different from clearing filters. Deleted attendance has a 30-day recoverable snapshot. Person removal erases biometrics and disables retained identities with historical records.
- Destructive changes require a confirmation dialog. Camera, profile and record actions stay permission-checked in the API. Roles remain institution-wide; this revision does not claim class-scoped teacher authorization.
- Refresh recovery uses an HttpOnly, SameSite=Strict browser cookie, checked against the existing server session on each page run. A single-use, 60-second exchange code installs it through a small local Streamlit component; browser scripts never receive the bearer token. Only configured dashboard origins may exchange or clear cookies. Cookies are not accepted as API authorization. Session expiry is fixed, and logout/password changes/account disabling invalidate the session. HTTPS sets Secure; the supported local HTTP setup uses loopback hosts.
- Live recognition uses the existing multi-face tracking and bounded inference pipeline. Its side panel shows identity, category, session, recorded event time and status. A bounded, session-local activity list shows recognition changes and errors; it is not an attendance record or a video archive.

## Validation boundary

API tests cover registration rollback, duplicate identities, encrypted templates, invalid authorization, category scoping, exports, dashboards and permissions. Streamlit tests exercise all accessible pages for each role, category sections, the wizard, profile actions, confirmation/cancellation, reset/recovery, live controls and form resets. Existing recognition, attendance, migration, launcher and export tests remain in the suite.

Browser checks use an isolated database with synthetic profiles; they do not alter operational attendance. Automated tests mock inference and do not certify real-camera accuracy. Local model loading/inference and hardware acceptance are separate checks. See [operations](operations.md) for deployment and biometric validation requirements.
