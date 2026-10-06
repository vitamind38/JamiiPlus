# Security, privacy and compliance checklist

From the build guide. This is a build checklist, not legal advice: confirm each item with a
data protection lawyer or the ODPC. "Built" means the code does it; it still needs checking
on the real deployment.

## Before the pilot (people and paperwork)

- [ ] Register with the ODPC as data controller or processor, if required.
- [ ] Data Protection Impact Assessment written and kept here: `docs/dpia.md` (template provided).
- [ ] Ethics approval (accredited committee), NACOSTI permit, county health department approval.
- [ ] Written agreement with the county: data owner, who sees which view, retention periods.
- [ ] Everything that can hold personal data runs on Kenyan infrastructure (the Compose stack is one server; choose a Kenyan provider).
- [x] Consent and privacy notice in Kiswahili and English, plain words, shown before first use — `mobile/lib/l10n/*.arb`, `NoticeScreen`; acceptance recorded on the server with its version.
- [ ] Have CHPs read the notice wording in a pre-test and fix what they misunderstand.

## Built into the system

- [x] TLS in transit (Caddy, automatic certificates; HSTS). Release app builds refuse plain HTTP.
- [ ] Encryption at rest: enable full-disk encryption on the server volume (provider setting). Backups are encrypted with `age` — built.
- [x] Role-based access, each role sees only its level — `services/scope.py`, tested in `tests/test_access.py`.
- [x] Supervisors see reports without CHP identity — pseudonyms only; phone numbers masked even for admins.
- [x] Audit log of who viewed or changed what, in a separate append-only database — `audit.py`, `infra/postgres/init/01-roles.sh`.
- [x] Automatic redaction before text is stored — `redaction.py` at intake; named-entity pass when approved; manual redaction queue if it fails.
- [x] Scheduled deletion of raw audio — nightly `purge_expired` plus a MinIO expiry rule as a backstop.
- [x] Secrets only in environment configuration — `infra/.env` (git-ignored); the app refuses dev keys outside local; CI runs gitleaks and `scripts/check_no_personal_data.py`.
- [x] Rate limits and lockout; codes expire quickly — 3 codes per 15 min, lockout after 5 wrong codes for 30 min, codes valid 5 min, 30 reports per hour.
- [ ] Tested backup restore before launch — `infra/scripts/restore_test.sh`; record the result in `docs/runbooks/backups.md`.
- [ ] Written breach-response plan, including who notifies the ODPC (within 72 hours) and the county.

## Product promises to CHPs, stated in the app

- [x] Reports are never used to discipline or rank individual CHPs — in the notice; the system has no per-CHP ranking anywhere, and dashboards only count by unit, ward and theme.
- [x] CHPs are told when a report led to action, or why it did not — every response goes out by SMS; "resolved without action" requires a reason.
- [x] CHPs can ask to have a report removed — app button, `REMOVE <id>` by SMS; content is deleted at once.
