# TalentGate ATS implementation instructions

This file is the working contract for completing the ATS gaps in this Flask, Neon PostgreSQL, Cloudinary recruitment and aptitude-assessment platform.

## Product decisions

- Implement one pipeline stage per pass. Do not begin the next stage until the current stage is tested, screenshotted, summarized, and confirmed complete.
- Keep the existing single shared admin login. Do not build Super Admin, Recruiter, Hiring Manager, Interviewer, or other admin accounts unless the product owner explicitly changes this decision.
- Notifications must be configurable by notification type. Each type must support `auto-send on stage change` or `require explicit admin send`. Preserve each notification type's current behavior as its default. Never add an unconditional send as a shortcut.
- Do not send real email while developing or testing. Mock delivery and assert that the delivery function was not called. Use a deliberate, separately approved production test for delivery.
- Keep one application per candidate email for now. Do not introduce multi-application candidate/application separation without a new product decision.
- Use the Aptus brand profile for the white-label edition and keep Mainstreet available as a separate deployment profile. Brand selection is deployment configuration, never a user-controlled tenant selector.
- Use separate Neon databases for independent customer deployments. Do not mix Mainstreet and Aptus candidate data in one deployment.

## Design instructions

Apply the Aptus design system to every new or redesigned screen. The white-label edition uses the same structure and behavior, with brand tokens supplied by its deployment profile.

- Use Deep Indigo (`#241E4E`) for navigation, headings, borders, and structural accents. Use Signal Teal (`#0FA3A3`) for primary actions, links, active states, and focus indicators. Both must appear on every screen.
- Use Off-White (`#F7F7F5`) for page backgrounds and cards, Charcoal (`#1E1E24`) for body text, Emerald (`#2E9E6B`) for success, Clay Red (`#C24545`) for errors, and Warm Amber (`#F2A93B`) only for small badges, progress, or notification highlights.
- Keep contrast at WCAG AA: Charcoal on Off-White and white on Indigo or Teal. Never use Amber as a page background or large surface.
- Use a geometric sans-serif such as Sora, Manrope, or Space Grotesk for headings and Inter or DM Sans for body text. Define fonts centrally and provide a system-font fallback.
- Follow a 4px/8px spacing grid. Prefer spacious layouts, clear grouping, short labels, visible status, and one obvious primary action per view.
- Design admin screens for dense but readable work: responsive tables, filter/search controls, sticky context where useful, empty/loading/error states, confirmation for destructive-looking actions, and clear validation beside fields.
- Design candidate screens for calm, transparent progress: explain the current stage, next step, timing, data use, and outcome in plain language. Avoid HR clichés and ambiguous calls to action.
- Make every flow keyboard accessible with visible focus, semantic labels, logical tab order, sufficient hit areas, reduced-motion support, and mobile layouts at narrow widths. Do not rely on color alone for status.
- Use the Aptus geometric funnel, gate, or checkmark mark concept. Do not introduce briefcase/handshake imagery or unrelated client colors.
- Keep design tokens in the shared theme/branding layer. Do not hardcode a second brand palette inside individual templates or components.

## Admin login details

- Login page: `/admin/login` (local URL: `http://127.0.0.1:5000/admin/login` when running Flask on the default port).
- Admin username: value of `ADMIN_USERNAME`; if unset, the application uses `admin`.
- Admin password: configure `ADMIN_PASSWORD_HASH` using the application's password-hash flow. The legacy `ADMIN_TOKEN` fallback exists for compatibility only and must be replaced before production.
- Store all credential values only in the uncommitted `.env` or deployment secret manager. Never paste the password, token, hash, session cookie, or recovery value into this document, tickets, screenshots, logs, or commits.
- After any credential appears in terminal output or another artifact, rotate it immediately. Use the logout action at `/admin/logout` and revoke active sessions when rotating credentials.
- Admin sessions expire after the configured inactivity window and are limited by the existing device/session controls. Preserve those controls in all redesigns.

## Stage loop

For every stage:

1. State the stage being implemented and the exact audit gaps it closes.
2. Inspect affected models, migrations, routes, templates, JavaScript, integrations, authorization, and existing conventions before editing.
3. If a required field, workflow, permission, notification behavior, or state transition is ambiguous, stop and ask the product owner. Do not guess.
4. Implement the smallest complete feature, including migrations, server routes, validation, admin UI, candidate behavior, and audit records where applicable.
5. Add automated tests using the repository's existing test pattern. If no test framework exists, use Python `unittest` rather than adding a dependency without approval.
6. Include negative tests for unauthorized access, CSRF failures, malformed input, invalid state transitions, stale updates, cross-candidate access, oversized files, and notification suppression when relevant.
7. Run focused tests, the full available test suite, Python compilation, and applicable security checks. Fix failures before continuing.
8. Capture screenshots of the actual admin-facing feature in use at desktop and mobile widths. Store artifacts under `output/playwright/`.
9. Report behavior, files changed, migrations, tests and results, screenshots, security decisions, and residual risks.
10. Stop and wait for explicit confirmation before starting the next stage.

## Stage order

Stage 1 is job requisitions and postings. It covers job records, department, location, employment type, description, requirements, optional application deadline, Draft → Published → Closed lifecycle, public job discovery, per-job application gating, migration of legacy roles, and review of unmatched historical applications. Existing candidate stages must remain unchanged when a job closes.

Stage 2 is interview feedback and scoring. Add structured interviewer scorecards, competency ratings, recommendation capture, submission state, and admin visibility linked to `interview_completed`. Do not infer competencies or rating scales; ask if the product does not specify them.

Stage 3 is offer management. Add offer records, terms, approval state, generated or uploaded offer artifacts, delivery state, acceptance, decline, negotiation, and immutable version history. Build on the existing `offered` stage and configurable notification behavior.

Stage 4 is onboarding handoff. Add accepted or hired state, start date, onboarding owner, handoff status, and a task checklist. Existing document collection may be reused, but document verification is not itself an onboarding handoff.

Stage 5 is rejection handling. Replace fixed `admin override` reasons with an explicit validated reason per rejection, preserve the reason in history, and apply the notification setting for rejection instead of always sending. Support rejection at every permitted stage without allowing candidates to alter it.

Stage 6 is sourcing and application intake. Add source and referral tracking, then reconcile cohort-whitelist intake with the public application path so both produce complete candidate records. Preserve one application per email unless the product decision changes.

Stage 7 is aptitude retakes. Add a configurable attempt limit and retained attempt history. Replace delete-and-reset behavior with a safe reassignment or new attempt model that never destroys prior scores, timing, tab-switch, or audit evidence.

Stage 8 is pipeline-wide reporting. Add a consolidated stage-count funnel, conversion rates, time-in-stage, and useful filters alongside existing assessment metrics and exports. Define metric denominators and timezone behavior before implementation.

Stage 9 is audit-trail completeness. Attribute actions beyond the generic `admin` label within the existing shared-login model, surface reasons in candidate history, and log resets, edits, document decisions, offers, notification actions, and other sensitive changes. Do not claim individual accountability that the shared credential cannot establish.

Stage 10 is admin-surface consolidation. Reconcile `/admin` and `/admin/recruitment`, or document a clear boundary between them. If it is unclear which surface should win, ask before merging or removing either surface.

Stage 11, role-based admin permissions, is explicitly skipped by product decision.

## Security constraints

Treat security as an acceptance criterion for every change. Preserve existing controls and fail closed when identity, authorization, state, or validation is uncertain.

- Authenticate every protected admin operation and authorize the specific action and record server-side. Never rely on hidden controls, route visibility, numeric IDs, or client-supplied roles.
- Keep the shared admin login unchanged unless explicitly approved. Do not expose credentials, session tokens, CSRF tokens, database URLs, Cloudinary secrets, SMTP passwords, or signed upload details in source, logs, URLs, screenshots, fixtures, or reports.
- Rotate any credential that appears in terminal output, screenshots, browser state, logs, commits, or generated artifacts.
- Validate all user-controlled values server-side with explicit type, length, format, enum, date, size, and state-transition checks. Normalize email addresses and reject null bytes and unsafe control characters.
- Use parameterized SQL. Allowlist dynamic sort columns, filters, identifiers, status values, and notification types. Never concatenate user input into SQL, shell commands, templates, redirects, or file paths.
- Use explicit mutable-field allowlists. Do not pass entire request dictionaries into database updates.
- Keep CSRF protection on every cookie-authenticated state change. Do not turn state-changing actions into GET requests.
- Use framework output escaping for HTML and context-appropriate encoding for attributes, JavaScript, URLs, CSS, emails, logs, and CSV exports. Do not introduce `innerHTML`, unsafe template filters, `eval`, or untrusted HTML without a reviewed sanitizer and narrow allowlist.
- Validate uploads by extension, MIME type, content signature, size, and storage destination. Reject active formats, generate storage names, authorize every preview/download, and never trust a client filename or Cloudinary public ID.
- Constrain outbound requests, proxies, redirects, and meeting integrations. Allowlist destinations, block internal and metadata networks where applicable, set timeouts, and avoid reflecting remote errors to users.
- Do not delete assessment attempts, candidate history, documents, offers, notification logs, or audit records to implement resets or corrections. Prefer append-only records, status changes, or reversible supersession.
- Use secure random tokens and maintained password/token primitives. Set secure cookie attributes in production and preserve session expiry, revocation, and device limits.
- Return generic production errors. Log enough for diagnosis without personal data, credentials, tokens, or document URLs. Preserve actor, action, record, reason, and timestamp for sensitive changes.
- Keep candidate data isolated by deployment/database. A brand or query parameter must never select another company's records.
- Do not weaken authorization or validation to make a test pass. If a requested behavior is unsafe, implement the safest compatible alternative and report the limitation.

## Data and migration rules

- Migrations must be idempotent, transactional where PostgreSQL permits, and safe to run more than once.
- Never use destructive cleanup, `DROP`, broad `DELETE`, truncation, or irreversible backfills without explicit approval and a reviewed backup/rollback plan.
- Preserve historical rows and unmatched records for review. Link legacy data only with an exact, documented match; never guess from partial names or email fragments.
- Add indexes for new admin list and reporting queries after checking query shape. Keep timestamps timezone-aware and document WAT versus UTC conversions.
- Record schema changes and data assumptions in the stage summary.

## Notification rules

- Add or extend a settings record keyed by notification type, with an allowlisted mode such as `auto` or `explicit`.
- Preserve current defaults for existing notification types.
- A stage transition may enqueue an email only when that type is configured for automatic delivery. Explicit notifications require a deliberate admin action with CSRF protection and an audit record.
- Never send notifications from tests, migrations, read-only previews, screenshots, or local UI checks. Mock the transport and assert calls.
- Do not place secrets or unnecessary candidate personal data in email URLs, subjects, logs, or error messages.

## Current handoff state

The Aptus profile is selected locally with `BRAND_PROFILE=aptus`. Stage 1 job-posting migration and initial routes exist, and the focused suite currently passes eight tests. The migration has been applied additively to the configured Neon database; it created seven closed legacy job postings, linked 70 candidates by exact role match, and left 242 unmatched historical applications visible for review.

Before declaring Stage 1 complete, finish the remaining lifecycle/application tests, verify the reorganized templates, fix any responsive job-list issues, capture desktop/mobile screenshots, and report the final diff. Do not begin Stage 2 until the product owner confirms Stage 1 is complete.
